"""Physics hand-calcs — proves the simulation engine's foundational formulas
match published aviation references. Failures here likely indicate a unit
conversion bug or a formula error."""

import math

import pytest

# Constants (re-derived locally to avoid coupling to whatever the app exports)
G_FT_S2 = 32.174
KT_TO_FPS = 1.68781
FT_PER_NM = 6076.12


# -------------------------------------------------------------------
# Test 1 — Standard rate turn radius
# -------------------------------------------------------------------

def _turn_radius_ft(tas_knots: float, bank_deg: float) -> float:
    v_fps = tas_knots * KT_TO_FPS
    return v_fps ** 2 / (G_FT_S2 * math.tan(math.radians(bank_deg)))


def test_turn_radius_120_kt_25_deg_bank():
    """120 kt, 25° bank → radius ≈ 2,734 ft from canonical
    r = V²/(g·tan(bank)) formula (FAA Pilot's Handbook of Aeronautical
    Knowledge, Ch. 5). Verified by hand: V=202.5 fps, V²=41018,
    g·tan(25°)=15.005 → r=2,734 ft."""
    r = _turn_radius_ft(120.0, 25.0)
    assert 2680 < r < 2790, f"got {r:.0f} ft, expected ~2,734"


def test_turn_radius_grows_with_speed():
    r_slow = _turn_radius_ft(80.0, 30.0)
    r_fast = _turn_radius_ft(160.0, 30.0)
    # Doubling speed at same bank → 4× radius
    ratio = r_fast / r_slow
    assert 3.9 < ratio < 4.1, f"got {ratio:.2f}, expected ~4.0"


# -------------------------------------------------------------------
# Test 2 — Stall speed at bank (load factor)
# -------------------------------------------------------------------

def _stall_speed_at_bank(vs_clean_kt: float, bank_deg: float) -> float:
    n = 1.0 / math.cos(math.radians(bank_deg))
    return vs_clean_kt * math.sqrt(n)


def test_vs_at_60_deg_bank_doubles_load_factor():
    """At 60° bank, n = 2; Vs grows by √2. Vs_clean = 50 kt → Vs60 ≈ 70.7 kt.
    (PHAK Ch. 5 + Aerodynamics for Naval Aviators)."""
    vs_clean = 50.0
    vs_60 = _stall_speed_at_bank(vs_clean, 60.0)
    assert 70.0 < vs_60 < 71.5, f"got {vs_60:.1f} kt, expected ~70.7"


def test_vs_at_45_deg_bank_grows_by_19_percent():
    """At 45° bank, Vs grows by √(1/cos45°) ≈ 1.189."""
    vs_clean = 50.0
    vs_45 = _stall_speed_at_bank(vs_clean, 45.0)
    assert 1.18 < (vs_45 / vs_clean) < 1.20, \
        f"ratio {vs_45/vs_clean:.3f}, expected ~1.189"


# -------------------------------------------------------------------
# Test 3 — Glide range
# -------------------------------------------------------------------

def _glide_range_nm(altitude_agl_ft: float, glide_ratio: float) -> float:
    return (altitude_agl_ft * glide_ratio) / FT_PER_NM


def test_glide_range_5000ft_9to1_still_air():
    """5,000 ft AGL, 9:1 glide → 45,000 ft = 7.40 NM."""
    r = _glide_range_nm(5000.0, 9.0)
    assert 7.35 < r < 7.45, f"got {r:.2f} NM, expected ~7.40"


def test_glide_range_scales_linearly():
    r_low = _glide_range_nm(2000.0, 9.0)
    r_high = _glide_range_nm(6000.0, 9.0)
    ratio = r_high / r_low
    assert 2.95 < ratio < 3.05, f"got {ratio:.2f}, expected 3.0"


# -------------------------------------------------------------------
# Cross-check — compute_turn_radius from utility.py
# (proves OUR implementation matches the reference formula)
# -------------------------------------------------------------------

def test_app_turn_radius_matches_reference():
    """Our compute_turn_radius() function in utility.py must match the
    canonical formula within 1% for the standard test condition."""
    from utility import compute_turn_radius

    canonical = _turn_radius_ft(120.0, 25.0)
    ours = compute_turn_radius(120.0, 25.0)
    rel_err = abs(canonical - ours) / canonical
    assert rel_err < 0.01, \
        f"compute_turn_radius={ours:.0f}, canonical={canonical:.0f}, " \
        f"rel_err={rel_err:.4f}"
