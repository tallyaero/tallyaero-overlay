"""
Aerodynamic calculations for aviation.
"""
import math

from .constants import g, rho_sl
from .atmosphere import compute_air_density


def compute_true_airspeed(ias_kts: float, pressure_alt_ft: float, oat_c: float) -> float:
    """
    Convert IAS to TAS using standard IAS->TAS scaling with local density.

    Args:
        ias_kts: Indicated airspeed in knots
        pressure_alt_ft: Pressure altitude in feet
        oat_c: Outside air temperature in Celsius

    Returns:
        True airspeed in knots
    """
    rho = compute_air_density(pressure_alt_ft, oat_c)
    return ias_kts / math.sqrt(rho / rho_sl)


def compute_turn_radius(tas_kts: float, bank_deg: float) -> float:
    """
    Calculate turn radius from true airspeed and bank angle.

    Args:
        tas_kts: True airspeed in knots
        bank_deg: Bank angle in degrees

    Returns:
        Turn radius in feet
    """
    tas_fps = tas_kts * 1.68781
    bank_rad = math.radians(bank_deg)
    return (tas_fps ** 2) / (g * math.tan(bank_rad))


def compute_required_bank(tas_kts: float, radius_ft: float) -> float:
    """
    Calculate required bank angle for a given turn radius.

    Args:
        tas_kts: True airspeed in knots
        radius_ft: Desired turn radius in feet

    Returns:
        Required bank angle in degrees
    """
    tas_fps = tas_kts * 1.68781
    return math.degrees(math.atan(tas_fps ** 2 / (g * radius_ft)))


def compute_glide_ratio(base_ratio: float, flap_config: str, gear_type: str, prop_config: str) -> float:
    """
    Calculate glide ratio with configuration adjustments.

    Args:
        base_ratio: Base glide ratio (clean configuration)
        flap_config: Flap configuration (clean/takeoff/landing)
        gear_type: Gear type (fixed/retractable)
        prop_config: Propeller configuration (feathered/stationary/windmilling/idle)

    Returns:
        Adjusted glide ratio
    """
    flap_drag = {"clean": 1.0, "takeoff": 1.1, "landing": 1.25}.get(flap_config, 1.0)
    gear_drag = 1.1 if gear_type == "retractable" else 1.0
    prop_drag = {"feathered": 1.0, "stationary": 1.2, "windmilling": 1.3, "idle": 1.05}.get(prop_config, 1.0)
    total_drag = flap_drag * gear_drag * prop_drag
    return base_ratio / total_drag


def compute_descent_angle_deg(glide_ratio: float) -> float:
    """
    Calculate descent angle from glide ratio.

    Args:
        glide_ratio: Glide ratio (horizontal distance / vertical distance)

    Returns:
        Descent angle in degrees
    """
    return math.degrees(math.atan(1 / glide_ratio))


def compute_Ps(thrust_lbf: float, drag_lbf: float, tas_fps: float, weight_lbf: float) -> float:
    """
    Calculate specific excess power (Ps).

    Args:
        thrust_lbf: Thrust in pounds force
        drag_lbf: Drag in pounds force
        tas_fps: True airspeed in feet per second
        weight_lbf: Weight in pounds

    Returns:
        Specific excess power in ft/s
    """
    return ((thrust_lbf - drag_lbf) * tas_fps) / weight_lbf


def compute_lift_limit_speed(cl_max: float, weight_lbf: float, rho: float, S: float) -> float:
    """
    Calculate maximum speed from aerodynamic limits.

    Args:
        cl_max: Maximum lift coefficient
        weight_lbf: Weight in pounds
        rho: Air density in slugs/ft^3
        S: Wing area in square feet

    Returns:
        Lift limit speed in fps
    """
    return math.sqrt((2 * weight_lbf) / (rho * cl_max * S))


def compute_load_factor(bank_deg: float) -> float:
    """
    Calculate load factor from bank angle.

    Args:
        bank_deg: Bank angle in degrees

    Returns:
        Load factor (g's)
    """
    return 1 / math.cos(math.radians(bank_deg))


def compute_stall_speed(clean_stall_kias: float, load_factor: float) -> float:
    """
    Calculate stall speed under load.

    Args:
        clean_stall_kias: Clean stall speed in KIAS
        load_factor: Load factor (g's)

    Returns:
        Stall speed under load in KIAS
    """
    return clean_stall_kias * math.sqrt(load_factor)
