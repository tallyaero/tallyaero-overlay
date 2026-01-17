"""
Atmospheric calculations for aviation.
"""
import math

from .constants import R, P_sl, rho_sl


def compute_density_altitude(oat_c: float, pressure_alt_ft: float) -> float:
    """
    Calculate density altitude from outside air temperature and pressure altitude.

    Args:
        oat_c: Outside air temperature in Celsius
        pressure_alt_ft: Pressure altitude in feet

    Returns:
        Density altitude in feet
    """
    isa_temp_c = 15 - 2 * (pressure_alt_ft / 1000.0)
    density_alt = pressure_alt_ft + (120 * (oat_c - isa_temp_c))
    return density_alt


def compute_pressure_altitude(indicated_alt_ft: float, altimeter_inhg: float) -> float:
    """
    Calculate pressure altitude from indicated altitude and altimeter setting.

    Args:
        indicated_alt_ft: Indicated altitude in feet
        altimeter_inhg: Altimeter setting in inches of mercury

    Returns:
        Pressure altitude in feet
    """
    return indicated_alt_ft + (29.92 - altimeter_inhg) * 1000


def compute_air_density(pressure_alt_ft: float, oat_c: float) -> float:
    """
    Calculate air density at a given pressure altitude and temperature.

    Args:
        pressure_alt_ft: Pressure altitude in feet
        oat_c: Outside air temperature in Celsius

    Returns:
        Air density in slugs/ft^3
    """
    temp_r = (oat_c + 273.15) * 9 / 5
    pressure_psf = P_sl * (1 - 0.0000068756 * pressure_alt_ft) ** 5.2561  # lbf/ft^2
    rho = pressure_psf / (R * temp_r)
    return rho


def adjust_glide_ratio_for_density(glide_ratio: float, rho: float) -> float:
    """
    Adjust glide ratio for air density effects.

    Args:
        glide_ratio: Base glide ratio
        rho: Current air density in slugs/ft^3

    Returns:
        Adjusted glide ratio (minimum 3.5)
    """
    factor = (rho / rho_sl) ** 0.3
    return max(glide_ratio * factor, 3.5)
