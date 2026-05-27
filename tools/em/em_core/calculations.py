# core/calculations.py

"""
Centralized aerodynamic + performance calculations.
All Ps, drag, thrust, stall, turn rate, turn radius math lives here.
This makes the EM app modular, testable, and faster.

This is the SINGLE SOURCE OF TRUTH for all physics calculations.
Both the EM Diagram and Maneuver Overlay tools must use these functions.
"""

import numpy as np
import math

# =============================================================================
# PHYSICAL CONSTANTS
# =============================================================================
g = 32.174              # Gravity, ft/s²
G_FT_S2 = 32.174        # Alias for clarity
KTS_TO_FPS = 1.68781    # Knots to feet per second
FPS_TO_KTS = 1 / 1.68781
KTS_TO_MPH = 1.15078    # Knots to miles per hour
RHO_SL = 0.002377       # Sea level air density, slugs/ft³
TEMP_SL_K = 288.15      # Sea level standard temperature, Kelvin
TEMP_SL_C = 15.0        # Sea level standard temperature, Celsius
LAPSE_RATE_K_FT = 0.0019812  # Temperature lapse rate, K per ft

def compute_dynamic_pressure(rho, V):
    """q = 0.5 * rho * V^2"""
    return 0.5 * rho * (V ** 2)


def compute_cl(weight, load_factor, q, wing_area, cl_max):
    """
    CL = W * n / (q S) with clipping at CL_max.
    """
    if q <= 0:
        return 0.0
    CL = weight * load_factor / (q * wing_area)
    return min(CL, cl_max)


def compute_cd(CD0, CL, AR, e, cg_drag_factor=1.0, gear_drag_factor=1.0, *,
               cd_rise=None):
    """
    CD = (CD0 + induced + rise) * CG_factor * gear_factor

    Where:
        induced = CL² / (π · AR · e)        — pure parabolic polar
        rise    = k · max(0, CL - CL₀)²     — high-CL drag rise (optional)

    Phase 2g: `cd_rise` is an optional per-aircraft dict
    `{"cl_threshold": X, "k_rise": Y}` that models the super-parabolic
    drag rise near stall (flow separation tip effects). Important for
    accurate Ps in steep turns and high-AOA flight. When unset, the
    polar is purely parabolic (the legacy behavior).
    """
    induced = (CL ** 2) / (math.pi * AR * e)
    CD = CD0 + induced
    if cd_rise:
        cl_threshold = cd_rise.get("cl_threshold")
        k_rise       = cd_rise.get("k_rise", 0.0)
        if cl_threshold is not None and k_rise:
            # np.maximum works on scalars + arrays, so this stays vectorized
            excess = np.maximum(0.0, np.asarray(CL) - cl_threshold)
            CD = CD + k_rise * excess ** 2
    return CD * cg_drag_factor * gear_drag_factor


def compute_drag(q, wing_area, CD):
    """D = q S CD"""
    return q * wing_area * CD


def compute_thrust_available(hp, V_kts, V_max_kts, T_static_factor):
    """
    T_static = T_static_factor * hp
    Thrust available decays quadratically with airspeed.
    """
    T_static = T_static_factor * hp
    V_fraction = np.clip(V_kts / V_max_kts, 0, 1)
    T_available = T_static * (1 - V_fraction ** 2)
    return max(T_available, 0)


def compute_ps_knots_per_sec(T, D, V_fps, weight, gamma_deg):
    """
    Compute specific excess power in knots/second.

    Ps = ((T - D) * V / W - V * sin(gamma)) / KTS_TO_FPS

    The V*sin(gamma) term subtracts the vertical velocity component,
    giving the energy rate available for acceleration only.

    Args:
        T: Thrust in lbs
        D: Drag in lbs
        V_fps: Velocity in ft/s
        weight: Aircraft weight in lbs
        gamma_deg: Flight path angle in degrees

    Returns:
        Ps in knots/second
    """
    gamma = math.radians(gamma_deg)
    ps_fps = (T - D) * (V_fps / weight) - V_fps * math.sin(gamma)
    return ps_fps / KTS_TO_FPS


# =============================================================================
# ATMOSPHERIC CALCULATIONS
# =============================================================================

def compute_air_density(altitude_ft, oat_c=None):
    """
    Compute air density at altitude.

    If oat_c is provided, uses actual temperature for density altitude effect.
    Otherwise uses standard atmosphere temperature lapse.

    Args:
        altitude_ft: Pressure altitude in feet
        oat_c: Outside air temperature in Celsius (optional)

    Returns:
        Air density in slugs/ft³
    """
    if oat_c is not None:
        # Use actual OAT to compute density altitude effect
        isa_temp_c = TEMP_SL_C - (altitude_ft * LAPSE_RATE_K_FT)
        temp_dev_c = oat_c - isa_temp_c
        density_alt = altitude_ft + (120 * temp_dev_c)
        temp_k = TEMP_SL_K - (density_alt * LAPSE_RATE_K_FT)
    else:
        # Standard atmosphere
        temp_k = TEMP_SL_K - (altitude_ft * LAPSE_RATE_K_FT)

    # Ensure temperature doesn't go negative (stratosphere simplification)
    temp_k = max(temp_k, 216.65)

    rho = RHO_SL * (temp_k / TEMP_SL_K) ** 4.256
    return rho


def compute_density_altitude(pressure_alt_ft, oat_c):
    """
    Compute density altitude from pressure altitude and OAT.

    DA = PA + 120 * (OAT - ISA_temp)

    Args:
        pressure_alt_ft: Pressure altitude in feet
        oat_c: Outside air temperature in Celsius

    Returns:
        Density altitude in feet
    """
    isa_temp_c = TEMP_SL_C - (pressure_alt_ft * LAPSE_RATE_K_FT)
    temp_dev_c = oat_c - isa_temp_c
    return pressure_alt_ft + (120 * temp_dev_c)


def compute_energy_state(altitude_ft, ias_kt):
    """Phase 5V — Specific energy decomposition of the current flight state.

    Total specific energy is E = h + V²/(2g) (in feet of altitude-equivalent),
    a.k.a. "energy height" in the Rutowski 1954 / Boyd 1966 formulation. It
    splits cleanly into:
        PE = h          (altitude → all potential energy)
        KE = V²/(2g)    (kinematic energy in altitude-equivalent units)

    This is the math underneath the FAA AFH Ch 4 (2021) "energy management"
    pedagogy — throttle adds total E, elevator redistributes between KE/PE.

    Args:
        altitude_ft: current altitude in feet MSL
        ias_kt: current indicated airspeed in knots

    Returns:
        dict with keys:
            ke_ft         — kinetic energy expressed as altitude-equivalent
            pe_ft         — potential energy (altitude itself)
            e_total_ft    — total specific energy
            ke_fraction   — KE / E_total, in [0, 1]
    """
    altitude_ft = altitude_ft or 0
    ias_kt = ias_kt or 0
    v_fps = ias_kt * KTS_TO_FPS
    ke_ft = (v_fps * v_fps) / (2.0 * g)
    pe_ft = float(altitude_ft)
    e_total_ft = ke_ft + pe_ft
    ke_fraction = (ke_ft / e_total_ft) if e_total_ft > 0 else 0.0
    return {
        "ke_ft":       ke_ft,
        "pe_ft":       pe_ft,
        "e_total_ft":  e_total_ft,
        "ke_fraction": ke_fraction,
    }


def compute_pressure_altitude(field_elev_ft, altimeter_inhg):
    """
    Compute pressure altitude from field elevation and altimeter setting.

    PA = Field Elev + (29.92 - altimeter) * 1000

    Args:
        field_elev_ft: Field elevation in feet MSL
        altimeter_inhg: Altimeter setting in inches Hg

    Returns:
        Pressure altitude in feet
    """
    return field_elev_ft + (29.92 - altimeter_inhg) * 1000


def compute_true_airspeed(ias_kts, density_alt_ft):
    """
    Compute TAS from IAS and density altitude.

    TAS = IAS / sqrt(sigma) where sigma = rho/rho_0

    Approximation: TAS ≈ IAS * (1 + 0.02 * DA/1000)

    Args:
        ias_kts: Indicated airspeed in knots
        density_alt_ft: Density altitude in feet

    Returns:
        True airspeed in knots
    """
    # Compute density ratio
    temp_k = TEMP_SL_K - (density_alt_ft * LAPSE_RATE_K_FT)
    temp_k = max(temp_k, 216.65)
    sigma = (temp_k / TEMP_SL_K) ** 4.256

    if sigma <= 0:
        sigma = 0.001

    return ias_kts / math.sqrt(sigma)


# =============================================================================
# TURN PHYSICS (Coordinated Flight)
# =============================================================================

def compute_load_factor(bank_deg):
    """
    Compute load factor (G) for a coordinated level turn.

    n = 1 / cos(bank)

    Args:
        bank_deg: Bank angle in degrees

    Returns:
        Load factor (G units)
    """
    bank_rad = math.radians(abs(bank_deg))
    cos_bank = math.cos(bank_rad)

    # Prevent division by zero near 90°
    if cos_bank < 0.01:
        cos_bank = 0.01

    return 1.0 / cos_bank


def compute_turn_rate_from_bank(tas_kts, bank_deg):
    """
    Compute turn rate for coordinated flight from bank angle.

    omega = g * tan(bank) / V

    Args:
        tas_kts: True airspeed in knots
        bank_deg: Bank angle in degrees

    Returns:
        Turn rate in degrees per second
    """
    if abs(bank_deg) < 0.1:
        return 0.0

    tas_fps = tas_kts * KTS_TO_FPS
    if tas_fps < 1.0:
        return 0.0

    bank_rad = math.radians(abs(bank_deg))
    omega_rad_s = (g * math.tan(bank_rad)) / tas_fps

    return math.degrees(omega_rad_s)


def compute_turn_rate_from_load_factor(tas_kts, load_factor):
    """
    Compute turn rate from load factor.

    omega = g * sqrt(n² - 1) / V

    This is the inverse relationship used for EM diagram curves.

    Args:
        tas_kts: True airspeed in knots
        load_factor: Load factor (G)

    Returns:
        Turn rate in degrees per second
    """
    if load_factor <= 1.0:
        return 0.0

    tas_fps = tas_kts * KTS_TO_FPS
    if tas_fps < 1.0:
        return 0.0

    omega_rad_s = g * math.sqrt(load_factor ** 2 - 1) / tas_fps
    return math.degrees(omega_rad_s)


def compute_turn_radius(tas_kts, bank_deg):
    """
    Compute turn radius for coordinated flight.

    R = V² / (g * tan(bank))

    Args:
        tas_kts: True airspeed in knots
        bank_deg: Bank angle in degrees

    Returns:
        Turn radius in feet
    """
    if abs(bank_deg) < 1.0:
        return float('inf')  # Straight flight

    tas_fps = tas_kts * KTS_TO_FPS
    bank_rad = math.radians(abs(bank_deg))
    tan_bank = math.tan(bank_rad)

    if tan_bank < 0.001:
        return float('inf')

    return (tas_fps ** 2) / (g * tan_bank)


def compute_bank_from_turn_rate(tas_kts, turn_rate_dps):
    """
    Compute required bank angle for a given turn rate.

    bank = atan(omega * V / g)

    Args:
        tas_kts: True airspeed in knots
        turn_rate_dps: Turn rate in degrees per second

    Returns:
        Required bank angle in degrees
    """
    if abs(turn_rate_dps) < 0.1:
        return 0.0

    tas_fps = tas_kts * KTS_TO_FPS
    omega_rad_s = math.radians(abs(turn_rate_dps))

    tan_bank = (omega_rad_s * tas_fps) / g
    return math.degrees(math.atan(tan_bank))


# =============================================================================
# STALL SPEED CALCULATIONS
# =============================================================================

def compute_stall_speed_at_load_factor(vs_1g, load_factor):
    """
    Compute accelerated stall speed.

    Vs_n = Vs_1g * sqrt(n)

    Args:
        vs_1g: 1G stall speed in knots
        load_factor: Load factor (G)

    Returns:
        Accelerated stall speed in knots
    """
    if load_factor < 0:
        load_factor = abs(load_factor)
    if load_factor < 0.1:
        load_factor = 0.1

    return vs_1g * math.sqrt(load_factor)


def interpolate_stall_speed(stall_data, weight):
    """
    Interpolate stall speed from aircraft JSON stall_speeds data.

    Aircraft JSON has format:
    {
        "weights": [2000, 2300, 2550],
        "speeds": [47, 50, 53]
    }

    Args:
        stall_data: Dict with 'weights' and 'speeds' lists
        weight: Current aircraft weight in lbs

    Returns:
        Interpolated stall speed in knots
    """
    weights = stall_data.get("weights", [])
    speeds = stall_data.get("speeds", [])

    if not weights or not speeds:
        if speeds and len(speeds) > 0:
            return speeds[0]
        return 50.0  # Fallback default

    if len(weights) != len(speeds):
        return speeds[0]

    # Use numpy interpolation
    return float(np.interp(weight, weights, speeds))


def compute_stall_ias_at_turn_rate(weight, rho, wing_area, cl_max, turn_rate_dps):
    """
    Compute the stall IAS for a given turn rate.

    From turn rate, compute load factor, then stall speed.
    This is used to generate the stall boundary curve.

    n = sqrt(1 + (omega * V / g)²)
    V_stall = sqrt(2 * W * n / (rho * S * CL_max))

    Args:
        weight: Aircraft weight in lbs
        rho: Air density in slugs/ft³
        wing_area: Wing area in ft²
        cl_max: Maximum lift coefficient
        turn_rate_dps: Turn rate in degrees per second

    Returns:
        Stall IAS in knots, or None if invalid
    """
    # This is an iterative problem since n depends on V
    # Use iteration to solve

    omega_rad_s = math.radians(abs(turn_rate_dps))

    # Initial guess: 1G stall speed
    v_stall_fps = math.sqrt((2 * weight) / (rho * wing_area * cl_max))

    # Iterate to convergence
    for _ in range(10):
        n = math.sqrt(1 + (v_stall_fps * omega_rad_s / g) ** 2)
        v_stall_fps_new = math.sqrt((2 * weight * n) / (rho * wing_area * cl_max))

        if abs(v_stall_fps_new - v_stall_fps) < 0.1:
            break
        v_stall_fps = v_stall_fps_new

    return v_stall_fps * FPS_TO_KTS
