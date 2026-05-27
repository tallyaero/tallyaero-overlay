"""Phase 5V — tests for the KE/PE energy-state decomposition.

The math is `E = h + V²/(2g)` with `g = 32.174 ft/s²`. KE expressed as
altitude-equivalent so KE and PE add cleanly. This is the FAA AFH Ch 4
(2021) "energy management" pedagogy made quantitative.
"""

from __future__ import annotations

import pytest

from core import compute_energy_state


# 1 KIAS = 1.68781 fps, so V_fps² / (2·g) at 100 KIAS:
#   V_fps = 168.781, V² = 28487, KE = 28487 / 64.348 = 442.7 ft
# (Note: this is *indicated* airspeed; the function treats it as TAS for the
# energy computation, which is correct for didactic constant-IAS purposes.)
EXPECTED_KE_100_KT = 442.7


class TestBasicComputation:
    def test_sea_level_stationary(self):
        e = compute_energy_state(0, 0)
        assert e["ke_ft"] == 0
        assert e["pe_ft"] == 0
        assert e["e_total_ft"] == 0
        assert e["ke_fraction"] == 0

    def test_sea_level_100kt(self):
        e = compute_energy_state(0, 100)
        assert e["ke_ft"] == pytest.approx(EXPECTED_KE_100_KT, abs=1.0)
        assert e["pe_ft"] == 0
        assert e["e_total_ft"] == pytest.approx(EXPECTED_KE_100_KT, abs=1.0)
        assert e["ke_fraction"] == pytest.approx(1.0, abs=0.001)

    def test_altitude_only_no_speed(self):
        e = compute_energy_state(10000, 0)
        assert e["ke_ft"] == 0
        assert e["pe_ft"] == 10000
        assert e["e_total_ft"] == 10000
        assert e["ke_fraction"] == 0

    def test_high_altitude_high_speed(self):
        """At cruise altitude + cruise speed, energy is mostly PE."""
        e = compute_energy_state(10000, 120)
        # KE at 120 kt: 168.781 * (120/100) → V²/(2g) ≈ 638 ft
        assert e["ke_ft"] == pytest.approx(637.5, abs=1.0)
        assert e["pe_ft"] == 10000
        assert e["e_total_ft"] == pytest.approx(10637.5, abs=2.0)
        # KE is 6% of total at cruise — exactly the AFH Ch 4 lesson
        assert 0.05 < e["ke_fraction"] < 0.07


class TestEdgeCases:
    def test_none_inputs(self):
        """None defaults to zero (the empty-state path)."""
        e = compute_energy_state(None, None)
        assert e["e_total_ft"] == 0
        assert e["ke_fraction"] == 0

    def test_negative_altitude_treated_as_value(self):
        """Death Valley / Salt Lake — negative MSL is legitimate."""
        e = compute_energy_state(-200, 100)
        assert e["pe_ft"] == -200
        assert e["ke_ft"] == pytest.approx(EXPECTED_KE_100_KT, abs=1.0)
        assert e["e_total_ft"] == pytest.approx(EXPECTED_KE_100_KT - 200, abs=2.0)


class TestEnergyConservation:
    """The whole point: trade altitude for airspeed at constant total energy."""

    def test_zoom_climb_equivalent(self):
        """A pilot at 1000 ft and 130 kt zooming to slow flight at higher
        altitude should land on the same constant-energy curve."""
        e_low_fast = compute_energy_state(1000, 130)
        # E = 1000 + (130 * 1.68781)² / (2 * 32.174)
        #   = 1000 + 219.4² / 64.348
        #   = 1000 + 748.2 ≈ 1748.2 ft
        assert e_low_fast["e_total_ft"] == pytest.approx(1748.2, abs=2.0)

        # Climbing to the equivalent zero-speed altitude
        e_high_slow = compute_energy_state(1748, 0)
        assert e_high_slow["e_total_ft"] == pytest.approx(e_low_fast["e_total_ft"], abs=2.0)

    def test_constant_e_diagonal(self):
        """For a fixed total energy, KE + PE must equal that constant."""
        # Three points on roughly the same constant-energy curve
        e1 = compute_energy_state(0, 130)        # ~ 741 ft total
        e2 = compute_energy_state(370, 95)       # ~ 395 + 370 = 765 (close)
        # They won't be identical (rounding to nice numbers) but close
        assert abs(e1["e_total_ft"] - e2["e_total_ft"]) < 100
