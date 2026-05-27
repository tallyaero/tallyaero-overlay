"""Phase 5R-3 — parametric tests for the Dynamic Vmc calculation.

The audit's central assertion is that at certified conditions
(14 CFR 23.149) the function returns exactly `published_vmca`. From there,
modifier sweeps must move Vmc in the documented direction.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.vmca import calculate_vmca


# Baron 58 reference — published Vmca = 84 KIAS at max weight 5500 lb, aft CG
BARON_PUB = 84
BARON_REF_W = 5500
BARON_CG_RANGE = [15.0, 22.0]   # forward 15", aft 22"
BARON_CG_AFT = 22.0


def _vmc(bank_deg: float, **overrides):
    """Convenience wrapper. Defaults to Baron 58 certified conditions."""
    defaults = dict(
        published_vmca=BARON_PUB,
        power_fraction=1.0,
        total_weight=BARON_REF_W,
        reference_weight=BARON_REF_W,
        cg=BARON_CG_AFT,
        cg_range=BARON_CG_RANGE,
        prop_condition="windmilling",
        pressure_altitude=0.0,
        oat_c=15.0,
        bank_angles_deg=np.array([bank_deg]),
    )
    defaults.update(overrides)
    _, vmc = calculate_vmca(**defaults)
    return float(vmc[0])


class TestCertifiedConditions:
    """Vmc at the certified state must equal published Vmca to the kt."""

    def test_baron_certified_returns_published(self):
        assert _vmc(5.0) == pytest.approx(BARON_PUB, abs=0.01)

    def test_certified_with_different_published_values(self):
        """The function should be calibrated for ANY published Vmca, not just 84."""
        for pub in [66, 70, 84, 95, 110]:
            assert _vmc(5.0, published_vmca=pub) == pytest.approx(pub, abs=0.01)


class TestBankSweep:
    """Bank angle effect: Vmc minimum at +5° (certified), rises both ways."""

    def test_bank_5_is_global_minimum(self):
        vmc_5 = _vmc(5.0)
        for b in [-5, -2, 0, 3, 8, 15, 30, 60]:
            assert _vmc(b) >= vmc_5, f"Vmc at {b}° should be >= Vmc at 5°"

    def test_negative_bank_penalty(self):
        """Banking away from the operating engine = no rudder aid + sideslip."""
        assert _vmc(-5.0) > _vmc(0.0) > _vmc(5.0)

    def test_high_bank_load_factor_penalty(self):
        """Beyond 5°, Vmc rises with load factor in the turn."""
        assert _vmc(60.0) > _vmc(30.0) > _vmc(10.0) > _vmc(5.0)


class TestWeightModifier:
    """Lighter aircraft → higher Vmc (less yaw inertia)."""

    def test_lighter_is_higher(self):
        certified = _vmc(5.0, total_weight=BARON_REF_W)
        lighter = _vmc(5.0, total_weight=4000)
        assert lighter > certified

    def test_weight_modifier_magnitude(self):
        """At ~70% of reference weight, Vmc should rise by 5-15%."""
        vmc_light = _vmc(5.0, total_weight=BARON_REF_W * 0.70)
        rise_pct = (vmc_light - BARON_PUB) / BARON_PUB * 100
        assert 3 < rise_pct < 20, f"weight rise {rise_pct:.1f}% out of band"


class TestPropConditionModifier:
    """Feathered prop reduces drag dramatically → lower Vmc."""

    def test_feathered_lower_than_windmilling(self):
        wind = _vmc(5.0, prop_condition="windmilling")
        feat = _vmc(5.0, prop_condition="feathered")
        assert feat < wind

    def test_feathered_reduction_matches_published_guidance(self):
        """Kershner / Lowery cite 10-15% Vmc reduction when feathered."""
        wind = _vmc(5.0, prop_condition="windmilling")
        feat = _vmc(5.0, prop_condition="feathered")
        reduction_pct = (wind - feat) / wind * 100
        assert 8 < reduction_pct < 16, f"feathered reduction {reduction_pct:.1f}% out of band"

    def test_stationary_between_windmilling_and_feathered(self):
        wind = _vmc(5.0, prop_condition="windmilling")
        stat = _vmc(5.0, prop_condition="stationary")
        feat = _vmc(5.0, prop_condition="feathered")
        assert feat < stat < wind


class TestCGModifier:
    """Forward CG → shorter rudder arm? No: forward CG = longer rudder arm.
    Per AC 23-8 the effect is "aft CG is most adverse" so published Vmc is
    at aft CG. Forward CG reduces Vmc slightly."""

    def test_forward_cg_lower(self):
        aft = _vmc(5.0, cg=BARON_CG_AFT)
        fwd = _vmc(5.0, cg=BARON_CG_RANGE[0])
        assert fwd < aft

    def test_certified_cg_is_aft(self):
        """Confirm aft CG yields the published value (it IS the certified condition)."""
        assert _vmc(5.0, cg=BARON_CG_AFT) == pytest.approx(BARON_PUB, abs=0.01)


class TestAltitudeModifier:
    """Higher altitude → engine power drops → less asymmetric thrust → lower Vmc."""

    def test_high_altitude_lower(self):
        sl = _vmc(5.0, pressure_altitude=0)
        high = _vmc(5.0, pressure_altitude=15000)
        assert high < sl

    def test_altitude_floor(self):
        """Modifier is clipped at 0.85 to prevent unreasonable reductions."""
        very_high = _vmc(5.0, pressure_altitude=40000)
        # At extreme altitude, Vmc shouldn't drop below 85% of published
        assert very_high >= BARON_PUB * 0.84


class TestPowerModifier:
    """Lower power on operating engine → less asymmetric thrust → lower Vmc."""

    def test_lower_power_lower_vmc(self):
        full = _vmc(5.0, power_fraction=1.0)
        half = _vmc(5.0, power_fraction=0.5)
        assert half < full

    def test_idle_power_clamped(self):
        """Below 0% net thrust, Vmc shouldn't keep dropping. Floor at 0.70."""
        idle = _vmc(5.0, power_fraction=0.05)
        full = _vmc(5.0, power_fraction=1.0)
        assert idle >= full * 0.70 - 0.5  # small tolerance for rounding
