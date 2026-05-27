"""
Unit tests for core/calculations.py.

Verifies every public function against known-good numerical results and
exercises edge cases that previously bit the codebase (per PHYSICS_AUDIT_PLAN.md
sessions 1–7).

Run with:
    make test
    # or
    venv/bin/pytest -v tests/test_core.py
"""

import math
import pytest

from core.calculations import (
    # Constants
    g,
    KTS_TO_FPS,
    FPS_TO_KTS,
    RHO_SL,
    # Aerodynamics
    compute_dynamic_pressure,
    compute_cl,
    compute_cd,
    compute_drag,
    compute_thrust_available,
    compute_ps_knots_per_sec,
    # Atmosphere
    compute_air_density,
    compute_density_altitude,
    compute_pressure_altitude,
    compute_true_airspeed,
    # Turn physics
    compute_load_factor,
    compute_turn_rate_from_bank,
    compute_turn_rate_from_load_factor,
    compute_turn_radius,
    compute_bank_from_turn_rate,
    # Stall
    compute_stall_speed_at_load_factor,
    interpolate_stall_speed,
    compute_stall_ias_at_turn_rate,
)


# =============================================================================
# AERODYNAMICS
# =============================================================================

class TestDynamicPressure:
    def test_sl_150fps(self):
        # q = 0.5 * 0.002377 * 150² = 26.74 lb/ft²
        q = compute_dynamic_pressure(RHO_SL, 150)
        assert q == pytest.approx(26.74, rel=1e-3)

    def test_zero_velocity(self):
        assert compute_dynamic_pressure(RHO_SL, 0) == 0.0

    def test_zero_density(self):
        assert compute_dynamic_pressure(0, 150) == 0.0


class TestCL:
    def test_normal(self):
        # q=30, weight=2000, n=1, S=160 → CL = 2000 / (30*160) = 0.417
        cl = compute_cl(weight=2000, load_factor=1, q=30, wing_area=160, cl_max=1.5)
        assert cl == pytest.approx(0.417, abs=0.005)

    def test_clipped_at_cl_max(self):
        # Tiny q forces enormous CL → must clip to cl_max
        cl = compute_cl(weight=2000, load_factor=1, q=0.1, wing_area=160, cl_max=1.5)
        assert cl == 1.5

    def test_q_zero_returns_zero(self):
        # Division-by-zero guard
        assert compute_cl(weight=2000, load_factor=1, q=0, wing_area=160, cl_max=1.5) == 0.0

    def test_q_negative_returns_zero(self):
        assert compute_cl(weight=2000, load_factor=1, q=-1, wing_area=160, cl_max=1.5) == 0.0


class TestCD:
    def test_parabolic_polar(self):
        # CD = CD0 + CL²/(π·AR·e)
        # 0.03 + 0.5²/(π·7·0.8) = 0.03 + 0.01421 = 0.04421
        cd = compute_cd(CD0=0.03, CL=0.5, AR=7.0, e=0.8)
        assert cd == pytest.approx(0.04421, abs=1e-4)

    def test_cg_factor_applied(self):
        cd_base = compute_cd(CD0=0.03, CL=0.5, AR=7.0, e=0.8, cg_drag_factor=1.0)
        cd_fwd = compute_cd(CD0=0.03, CL=0.5, AR=7.0, e=0.8, cg_drag_factor=1.04)
        assert cd_fwd == pytest.approx(cd_base * 1.04, rel=1e-6)

    def test_gear_factor_applied(self):
        cd_up = compute_cd(CD0=0.03, CL=0.5, AR=7.0, e=0.8, gear_drag_factor=1.0)
        cd_dn = compute_cd(CD0=0.03, CL=0.5, AR=7.0, e=0.8, gear_drag_factor=1.15)
        assert cd_dn == pytest.approx(cd_up * 1.15, rel=1e-6)

    def test_factors_compound(self):
        cd_clean = compute_cd(0.03, 0.5, 7.0, 0.8, 1.0, 1.0)
        cd_dirty = compute_cd(0.03, 0.5, 7.0, 0.8, 1.04, 1.15)
        assert cd_dirty == pytest.approx(cd_clean * 1.04 * 1.15, rel=1e-6)


class TestDrag:
    def test_basic(self):
        # D = q·S·CD = 30 * 160 * 0.04 = 192 lb
        d = compute_drag(q=30, wing_area=160, CD=0.04)
        assert d == pytest.approx(192.0)


class TestThrustAvailable:
    def test_static_thrust(self):
        # T = T_static_factor * hp at V=0
        T = compute_thrust_available(hp=160, V_kts=0, V_max_kts=140, T_static_factor=2.6)
        assert T == pytest.approx(2.6 * 160)

    def test_zero_at_vmax(self):
        # T_static * (1 - 1²) = 0
        T = compute_thrust_available(hp=160, V_kts=140, V_max_kts=140, T_static_factor=2.6)
        assert T == pytest.approx(0.0, abs=1e-6)

    def test_quadratic_decay(self):
        # At V=70, V/Vmax=0.5 → T = T_static * (1 - 0.25) = 0.75 * T_static
        T = compute_thrust_available(hp=160, V_kts=70, V_max_kts=140, T_static_factor=2.6)
        assert T == pytest.approx(0.75 * 2.6 * 160, rel=1e-6)

    def test_never_negative(self):
        # V above V_max should clip to V/Vmax = 1, yielding zero (not negative)
        T = compute_thrust_available(hp=160, V_kts=200, V_max_kts=140, T_static_factor=2.6)
        assert T >= 0.0


class TestPs:
    def test_level_flight_thrust_equals_drag(self):
        # T == D, gamma=0 → Ps = 0
        ps = compute_ps_knots_per_sec(T=300, D=300, V_fps=150, weight=2000, gamma_deg=0)
        assert ps == pytest.approx(0.0, abs=1e-9)

    def test_excess_thrust_accelerates(self):
        # T > D → positive Ps
        ps = compute_ps_knots_per_sec(T=400, D=300, V_fps=150, weight=2000, gamma_deg=0)
        assert ps > 0

    def test_climb_decreases_ps(self):
        # Same T/D but climbing: subtracts V·sin(γ) → less Ps available for acceleration
        ps_level = compute_ps_knots_per_sec(T=400, D=300, V_fps=150, weight=2000, gamma_deg=0)
        ps_climb = compute_ps_knots_per_sec(T=400, D=300, V_fps=150, weight=2000, gamma_deg=10)
        assert ps_climb < ps_level

    def test_descent_units_consistent(self):
        """Regression: Ps formula previously used g·sin(γ) instead of V·sin(γ).
        At γ=−10°, V=150 fps, the dive-energy term is 150·sin(-10°) = -26.05 fps,
        not 32.174·sin(-10°) = -5.59 fps. Verify the correct term is in use."""
        # Pure dive contribution (T=D=0): Ps_fps = -V·sin(γ) = -150·sin(-10) = +26.05 fps
        # → Ps_kts = 26.05 / 1.68781 = 15.43 kts/sec
        ps = compute_ps_knots_per_sec(T=0, D=0, V_fps=150, weight=2000, gamma_deg=-10)
        expected = -150 * math.sin(math.radians(-10)) / KTS_TO_FPS
        assert ps == pytest.approx(expected, rel=1e-6)


# =============================================================================
# ATMOSPHERE
# =============================================================================

class TestAirDensity:
    def test_sea_level_isa(self):
        rho = compute_air_density(0)
        assert rho == pytest.approx(RHO_SL, rel=1e-4)

    def test_density_decreases_with_altitude(self):
        rho_sl = compute_air_density(0)
        rho_10k = compute_air_density(10000)
        rho_20k = compute_air_density(20000)
        assert rho_10k < rho_sl
        assert rho_20k < rho_10k

    def test_hot_day_lower_density(self):
        """Hot day at the same pressure altitude = lower density."""
        rho_isa = compute_air_density(5000, oat_c=None)
        rho_hot = compute_air_density(5000, oat_c=35)  # 30°C above ISA
        assert rho_hot < rho_isa

    def test_stratosphere_floor(self):
        """Above ~36k ft, temperature is clamped (no negative absolute temps)."""
        # 100k ft would give absurd negative temp without the clamp
        rho = compute_air_density(100000)
        assert rho > 0


class TestDensityAltitude:
    def test_isa(self):
        # When OAT equals ISA temp at the given PA, DA == PA.
        # ISA at 5000 ft = 15 − 5000·0.0019812 = 5.094 °C (ICAO lapse, not the 2°C/1000ft rule).
        from core.calculations import TEMP_SL_C, LAPSE_RATE_K_FT
        isa_oat = TEMP_SL_C - 5000 * LAPSE_RATE_K_FT
        da = compute_density_altitude(5000, oat_c=isa_oat)
        assert da == pytest.approx(5000, abs=0.01)

    def test_hot_day(self):
        # PA=5000, OAT=30°C, ISA at 5k ≈ 5°C → ΔT=25°C → DA ≈ 5000 + 120*25 = 8000
        da = compute_density_altitude(5000, oat_c=30)
        assert da == pytest.approx(8000, abs=50)

    def test_cold_day(self):
        # PA=5000, OAT=−20°C, ΔT=−25°C → DA ≈ 5000 − 3000 = 2000
        da = compute_density_altitude(5000, oat_c=-20)
        assert da < 5000


class TestPressureAltitude:
    def test_standard_pressure(self):
        # 29.92 inHg → PA == field elev
        pa = compute_pressure_altitude(field_elev_ft=1000, altimeter_inhg=29.92)
        assert pa == pytest.approx(1000.0)

    def test_low_pressure_higher_pa(self):
        # 29.42 inHg (0.50 below standard) → PA = field + 500
        pa = compute_pressure_altitude(field_elev_ft=1000, altimeter_inhg=29.42)
        assert pa == pytest.approx(1500.0)

    def test_high_pressure_lower_pa(self):
        # 30.42 inHg (0.50 above standard) → PA = field − 500
        pa = compute_pressure_altitude(field_elev_ft=1000, altimeter_inhg=30.42)
        assert pa == pytest.approx(500.0)


class TestTrueAirspeed:
    def test_sl_tas_equals_ias(self):
        tas = compute_true_airspeed(ias_kts=100, density_alt_ft=0)
        assert tas == pytest.approx(100.0, abs=0.5)

    def test_increases_with_altitude(self):
        tas_sl = compute_true_airspeed(100, 0)
        tas_8k = compute_true_airspeed(100, 8000)
        tas_18k = compute_true_airspeed(100, 18000)
        assert tas_sl < tas_8k < tas_18k

    def test_8k_da_approx_2pct_per_1000(self):
        # Rule of thumb: TAS ≈ IAS·(1 + 0.02·DA/1000) → at 8000 ft ≈ 116 kts
        tas = compute_true_airspeed(100, 8000)
        assert 110 < tas < 120


# =============================================================================
# TURN PHYSICS
# =============================================================================

class TestLoadFactor:
    def test_level(self):
        assert compute_load_factor(0) == pytest.approx(1.0)

    def test_45deg(self):
        assert compute_load_factor(45) == pytest.approx(math.sqrt(2), abs=0.01)

    def test_60deg(self):
        assert compute_load_factor(60) == pytest.approx(2.0, abs=0.01)

    def test_negative_bank_same_as_positive(self):
        # Coordinated turn — sign of bank shouldn't change G
        assert compute_load_factor(-45) == pytest.approx(compute_load_factor(45))

    def test_near_90_clamped(self):
        """Regression: cos(90°)≈0 caused division-by-zero. Function must clamp."""
        n = compute_load_factor(89.9)
        assert math.isfinite(n)
        assert n > 0


class TestTurnRateFromBank:
    def test_45deg_100kts(self):
        # ω = g·tan(45°) / (100·1.68781) = 32.174 / 168.781 = 0.1906 rad/s = 10.92 °/s
        tr = compute_turn_rate_from_bank(100, 45)
        assert tr == pytest.approx(10.92, abs=0.05)

    def test_zero_bank_zero_rate(self):
        assert compute_turn_rate_from_bank(100, 0) == 0.0

    def test_low_tas_zero_rate(self):
        # Prevent absurd turn rates at near-zero airspeed (function returns 0 below 1 fps).
        # 0.1 kts = 0.17 fps → returns 0.
        assert compute_turn_rate_from_bank(0.1, 30) == 0.0


class TestTurnRadius:
    def test_45deg_100kts(self):
        # R = V²/(g·tan(45°)) = (168.78)² / 32.174 = 885 ft
        r = compute_turn_radius(100, 45)
        assert r == pytest.approx(885, abs=5)

    def test_zero_bank_infinite_radius(self):
        assert math.isinf(compute_turn_radius(100, 0))

    def test_small_bank_infinite_radius(self):
        # Function returns inf for |bank|<1° to avoid huge but finite radii
        assert math.isinf(compute_turn_radius(100, 0.5))


class TestTurnRateFromLoadFactor:
    def test_2g_100kts(self):
        # ω = g·√(4−1) / V = 32.174·1.732 / 168.78 = 0.330 rad/s = 18.93 °/s
        tr = compute_turn_rate_from_load_factor(100, 2.0)
        assert tr == pytest.approx(18.93, abs=0.1)

    def test_1g_zero_rate(self):
        assert compute_turn_rate_from_load_factor(100, 1.0) == 0.0

    def test_below_1g_zero_rate(self):
        assert compute_turn_rate_from_load_factor(100, 0.5) == 0.0


class TestBankFromTurnRate:
    def test_inverse_of_turn_rate_from_bank(self):
        # Round-trip: bank → rate → bank should be identity
        original_bank = 30.0
        tr = compute_turn_rate_from_bank(120, original_bank)
        bank = compute_bank_from_turn_rate(120, tr)
        assert bank == pytest.approx(original_bank, abs=0.01)


# =============================================================================
# STALL
# =============================================================================

class TestStallSpeedAtLoadFactor:
    def test_2g_stall(self):
        # Vs_n = Vs_1g · √n → 50 · √2 = 70.71
        assert compute_stall_speed_at_load_factor(50, 2.0) == pytest.approx(70.71, abs=0.05)

    def test_1g_returns_base(self):
        assert compute_stall_speed_at_load_factor(50, 1.0) == 50.0

    def test_negative_g_uses_absolute(self):
        # Symmetric: V_s(−2G) and V_s(+2G) should match (lift sign doesn't change stall speed)
        assert compute_stall_speed_at_load_factor(50, -2.0) == pytest.approx(
            compute_stall_speed_at_load_factor(50, 2.0)
        )

    def test_near_zero_clamped(self):
        # n→0 would give zero stall — function clamps to a tiny floor (n=0.1) so result is real
        vs = compute_stall_speed_at_load_factor(50, 0.0)
        assert math.isfinite(vs)
        assert vs > 0


class TestInterpolateStallSpeed:
    DATA = {"weights": [2000, 2300, 2550], "speeds": [47, 50, 53]}

    def test_interior(self):
        # 2150 lbs is midway-ish between 2000 and 2300 → ~48.5 kts
        vs = interpolate_stall_speed(self.DATA, 2150)
        assert vs == pytest.approx(48.5, abs=0.5)

    def test_at_endpoints(self):
        assert interpolate_stall_speed(self.DATA, 2000) == pytest.approx(47)
        assert interpolate_stall_speed(self.DATA, 2550) == pytest.approx(53)

    def test_extrapolation_low_clamps(self):
        # np.interp clamps at endpoints — no negative or below-stall extrapolation
        assert interpolate_stall_speed(self.DATA, 100) == pytest.approx(47)

    def test_extrapolation_high_clamps(self):
        assert interpolate_stall_speed(self.DATA, 10000) == pytest.approx(53)

    def test_empty_data_fallback(self):
        """Regression: empty `speeds` list previously raised IndexError."""
        vs = interpolate_stall_speed({"weights": [], "speeds": []}, 2000)
        assert vs == 50.0  # documented fallback

    def test_mismatched_lengths_returns_first(self):
        vs = interpolate_stall_speed({"weights": [2000, 2300], "speeds": [47]}, 2150)
        assert vs == 47

    def test_missing_keys(self):
        vs = interpolate_stall_speed({}, 2000)
        assert vs == 50.0


class TestStallIASAtTurnRate:
    def test_converges(self):
        # 2000 lb, SL density, 160 ft², CLmax 1.5, 5 °/s
        # Coupled iteration must converge to a sane stall IAS
        v = compute_stall_ias_at_turn_rate(
            weight=2000, rho=RHO_SL, wing_area=160, cl_max=1.5, turn_rate_dps=5
        )
        assert math.isfinite(v)
        assert 40 < v < 80  # ballpark sanity for trainer-class aircraft

    def test_zero_turn_rate_yields_1g_stall(self):
        """At ω=0, n=1 and v_stall reduces to the 1G stall."""
        v0 = compute_stall_ias_at_turn_rate(2000, RHO_SL, 160, 1.5, 0)
        # Compare against the analytic 1G stall: V = √(2W/(ρ·S·CLmax))
        v_analytic_fps = math.sqrt(2 * 2000 / (RHO_SL * 160 * 1.5))
        assert v0 == pytest.approx(v_analytic_fps * FPS_TO_KTS, abs=0.1)
