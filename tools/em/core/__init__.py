# core/__init__.py

"""
Core module containing physics calculations, constants, and data loading.
"""

from .logging_setup import setup_logging, get_logger, log_feature

# Initialize logging on first import of the core package so that any
# subsequent module-level log calls (e.g., aircraft_loader boot messages) are
# routed through the configured handler. Idempotent.
setup_logging()

from .constants import (
    DEBUG_LOG,
    DEFAULT_PASSENGER_WEIGHT,
    DEFAULT_FUEL_WEIGHT_PER_GAL,
    DEFAULT_POWER_SETTING,
    DEFAULT_ALTITUDE,
    DEFAULT_PITCH_ANGLE,
    HIGH_RES_SCREEN_WIDTH,
    HIGH_RES_AOB_IAS_STEP,
    HIGH_RES_TR_STEP,
    LOW_RES_AOB_IAS_STEP,
    LOW_RES_TR_STEP,
    DEFAULT_SCREEN_WIDTH,
    PS_CONTOUR_LEVELS,
    PS_GRID_POINTS,
    COLORS,
    STEEP_TURN_DEFAULT_AOB,
    STEEP_TURN_DEFAULT_IAS,
    CHANDELLE_DEFAULT_BANK,
    CHANDELLE_DEFAULT_IAS,
    PROP_DRAG_FACTORS,
)

from .calculations import (
    # Physical constants
    g, G_FT_S2, KTS_TO_FPS, FPS_TO_KTS, KTS_TO_MPH, RHO_SL, TEMP_SL_K, TEMP_SL_C, LAPSE_RATE_K_FT,
    # Drag/Lift calculations
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
    compute_energy_state,
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

from .vmca import calculate_vmca
from .vyse import calculate_dynamic_vyse
from .plotly_themes import get_palette as get_chart_palette

from .aircraft_loader import (
    AIRCRAFT_DATA,
    aircraft_data,
    init_data,
    load_aircraft_data_from_folder,
    extract_vmca_value,
    resource_path,
    DynamicAircraftData,
    dprint,
    # Airport data
    AIRPORT_DATA,
    AIRPORT_OPTIONS,
    get_airport_by_id,
)
