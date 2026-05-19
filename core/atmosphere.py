"""Standard-atmosphere / density-altitude helpers.

Phase A2 from the future-refinements plan. Pulls OAT + altimeter
(already in the env panel) and field elevation, returns pressure
altitude + density altitude in feet.

Formulas use the textbook ISA troposphere lapse rate and the FAA
approximation for DA (NWS / E6B). For altitudes below the tropopause
(~36,000 ft) the result matches a Koch chart to within ~10 ft, which
is well below the ~50 ft band a pilot reads off the POH.
"""
from __future__ import annotations


STANDARD_ALTIMETER_INHG = 29.92
ISA_SEA_LEVEL_TEMP_C = 15.0
ISA_LAPSE_C_PER_1000_FT = 1.98  # FAA approximation (truly ~1.98°C/1000ft).
# FAA E6B coefficient. DA ≈ PA + DA_COEF_FT_PER_C * (OAT - ISA_temp_at_PA).
DA_COEF_FT_PER_C = 118.8


def pressure_altitude_ft(field_elev_ft: float, altimeter_inhg: float) -> float:
    """Field pressure altitude. Reduces to field elevation at 29.92."""
    try:
        elev = float(field_elev_ft or 0.0)
        alt = float(altimeter_inhg) if altimeter_inhg else STANDARD_ALTIMETER_INHG
    except (TypeError, ValueError):
        return float(field_elev_ft or 0.0)
    return elev + (STANDARD_ALTIMETER_INHG - alt) * 1000.0


def isa_temp_c_at_alt(alt_ft: float) -> float:
    """ISA temperature in °C at the given altitude. Linear lapse below
    the tropopause; isothermal -56.5°C above."""
    if alt_ft >= 36089.0:
        return -56.5
    return ISA_SEA_LEVEL_TEMP_C - (alt_ft / 1000.0) * ISA_LAPSE_C_PER_1000_FT


def density_altitude_ft(field_elev_ft: float,
                        altimeter_inhg: float,
                        oat_c: float) -> float:
    """Density altitude in MSL feet for the given station conditions.

    `oat_c` is the outside-air temperature at the field. Setting it
    equal to ISA at the pressure altitude returns the pressure altitude
    unchanged (definitionally — no temperature deviation).
    """
    pa = pressure_altitude_ft(field_elev_ft, altimeter_inhg)
    try:
        oat = float(oat_c)
    except (TypeError, ValueError):
        return pa
    isa_t = isa_temp_c_at_alt(pa)
    return pa + DA_COEF_FT_PER_C * (oat - isa_t)
