"""Phase 5R-4 — parametric tests for the Dynamic Vyse calculation.

Same central assertion as test_vmc.py: at certified conditions (reference
weight, sea-level standard day, gear up, clean flaps, prop feathered) the
function must return exactly `published_vyse`. From there, modifier sweeps
must move Vyse in the documented direction.
"""

from __future__ import annotations

import pytest

from em_core.vyse import calculate_dynamic_vyse


# Baron 58 reference — published Vyse = 105 KIAS at certified conditions
BARON_PUB_VYSE = 105
BARON_REF_W = 5500


def _vyse(**overrides):
    """Convenience wrapper. Defaults to Baron 58 certified conditions."""
    defaults = dict(
        published_vyse=BARON_PUB_VYSE,
        total_weight=BARON_REF_W,
        reference_weight=BARON_REF_W,
        pressure_altitude=0.0,
        oat_c=15.0,
        gear_position="up",
        flap_config="clean",
        prop_condition="feathered",
    )
    defaults.update(overrides)
    return float(calculate_dynamic_vyse(**defaults))


class TestCertifiedConditions:
    """DVyse at the certified state must equal published Vyse exactly."""

    def test_baron_certified_returns_published(self):
        assert _vyse() == pytest.approx(BARON_PUB_VYSE, abs=0.01)

    def test_certified_with_different_published_values(self):
        for pub in [70, 88, 105, 122, 138]:
            assert _vyse(published_vyse=pub) == pytest.approx(pub, abs=0.01)


class TestWeightModifier:
    """Heavier aircraft → higher Vyse (need more speed for max excess power)."""

    def test_heavier_is_higher_or_equal(self):
        """Light weight should give lower or equal Vyse (clipped at 0.92×)."""
        heavy = _vyse(total_weight=BARON_REF_W)
        light = _vyse(total_weight=BARON_REF_W * 0.6)
        assert light <= heavy

    def test_weight_modifier_clipped(self):
        """Modifier is clipped to [0.92, 1.08] to keep DVyse defensible."""
        very_light = _vyse(total_weight=BARON_REF_W * 0.2)
        assert very_light >= BARON_PUB_VYSE * 0.91


class TestAltitudeModifier:
    """Higher altitude shifts the L/D bend up slightly → modest Vyse increase."""

    def test_high_altitude_higher_or_equal(self):
        sl = _vyse(pressure_altitude=0)
        high = _vyse(pressure_altitude=10000)
        assert high >= sl

    def test_altitude_modifier_clipped(self):
        """Bounded at 1.03× to prevent unreasonable extrapolation."""
        extreme = _vyse(pressure_altitude=40000)
        assert extreme <= BARON_PUB_VYSE * 1.04


class TestGearModifier:
    """Gear extended adds drag → optimal Vyse rises."""

    def test_gear_down_higher(self):
        up = _vyse(gear_position="up")
        down = _vyse(gear_position="down")
        assert down > up

    def test_gear_down_magnitude(self):
        """4% Vyse rise with gear down — defensible for a clean-up baseline."""
        up = _vyse(gear_position="up")
        down = _vyse(gear_position="down")
        assert down == pytest.approx(up * 1.04, abs=0.5)


class TestFlapModifier:
    """Flaps shift the drag curve, moving optimal Vyse up."""

    def test_landing_flaps_highest(self):
        clean = _vyse(flap_config="clean")
        takeoff = _vyse(flap_config="takeoff")
        landing = _vyse(flap_config="landing")
        assert clean < takeoff < landing

    def test_clean_is_certified_baseline(self):
        """Clean is the certified flap configuration — factor 1.0."""
        assert _vyse(flap_config="clean") == pytest.approx(BARON_PUB_VYSE, abs=0.01)


class TestPropConditionModifier:
    """Feathered = certified (max climb); windmilling adds drag → higher Vyse."""

    def test_feathered_is_certified(self):
        """Feathered must equal published — it IS the certified condition."""
        assert _vyse(prop_condition="feathered") == pytest.approx(BARON_PUB_VYSE, abs=0.01)

    def test_windmilling_higher_than_feathered(self):
        feat = _vyse(prop_condition="feathered")
        wind = _vyse(prop_condition="windmilling")
        assert wind > feat

    def test_windmilling_magnitude(self):
        """Windmilling Vyse should be 5-10% higher than feathered."""
        feat = _vyse(prop_condition="feathered")
        wind = _vyse(prop_condition="windmilling")
        rise_pct = (wind - feat) / feat * 100
        assert 4 < rise_pct < 12, f"windmilling rise {rise_pct:.1f}% out of band"

    def test_stationary_between(self):
        feat = _vyse(prop_condition="feathered")
        stat = _vyse(prop_condition="stationary")
        wind = _vyse(prop_condition="windmilling")
        assert feat < stat < wind


class TestCompoundConditions:
    """A realistic OEI scenario should produce a number a CFI-MEI would defend."""

    def test_realistic_baron_oei_scenario(self):
        """Engine fails just after liftoff — gear still down, clean flaps,
        windmilling prop, max weight, sea level. DVyse should be noticeably
        higher than the book number."""
        v = _vyse(
            gear_position="down",
            prop_condition="windmilling",
            flap_config="clean",
        )
        # Gear down (1.04) × windmilling (1.07) = 1.1128
        expected = BARON_PUB_VYSE * 1.04 * 1.07
        assert v == pytest.approx(expected, abs=0.5)
        # And the directional check: ~10-12% higher than book
        rise_pct = (v - BARON_PUB_VYSE) / BARON_PUB_VYSE * 100
        assert 9 < rise_pct < 14
