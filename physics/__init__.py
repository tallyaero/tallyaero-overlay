"""
Physics module for aviation calculations.
"""

from .constants import (
    g, G_FPS2, R, T_sl, P_sl, rho_sl,
    FT_PER_NM, FT_PER_M,
    OVERHEAD_THRESH_FT, FINAL_MIN_DIST_NM, FINAL_MAX_DIST_NM,
    FINAL_CROSSING_HEIGHT_FT, FINAL_ALIGN_TOL_DEG, DEFAULT_ALIGN_WINDOW_DEG
)

from .conversions import (
    knots_to_fps, fps_to_knots, fpm_to_fps, fps_to_fpm,
    celsius_to_fahrenheit, fahrenheit_to_celsius
)

from .atmosphere import (
    compute_density_altitude, compute_pressure_altitude,
    compute_air_density, adjust_glide_ratio_for_density
)

from .aerodynamics import (
    compute_true_airspeed, compute_turn_radius, compute_required_bank,
    compute_glide_ratio, compute_descent_angle_deg, compute_Ps,
    compute_lift_limit_speed, compute_load_factor, compute_stall_speed
)

from .navigation import (
    point_from, calculate_initial_compass_bearing,
    wind_components, estimate_energy_bleed_distance,
    _wrap_360, _angle_diff_deg, _bearing_to_unit_ne,
    _cross_track_distance_ft, _heading_from_track_components,
    _wind_components_from_dir, _local_xy_ft, _cross_track_to_centerline_ft
)

__all__ = [
    # Constants
    'g', 'G_FPS2', 'R', 'T_sl', 'P_sl', 'rho_sl',
    'FT_PER_NM', 'FT_PER_M',
    'OVERHEAD_THRESH_FT', 'FINAL_MIN_DIST_NM', 'FINAL_MAX_DIST_NM',
    'FINAL_CROSSING_HEIGHT_FT', 'FINAL_ALIGN_TOL_DEG', 'DEFAULT_ALIGN_WINDOW_DEG',
    # Conversions
    'knots_to_fps', 'fps_to_knots', 'fpm_to_fps', 'fps_to_fpm',
    'celsius_to_fahrenheit', 'fahrenheit_to_celsius',
    # Atmosphere
    'compute_density_altitude', 'compute_pressure_altitude',
    'compute_air_density', 'adjust_glide_ratio_for_density',
    # Aerodynamics
    'compute_true_airspeed', 'compute_turn_radius', 'compute_required_bank',
    'compute_glide_ratio', 'compute_descent_angle_deg', 'compute_Ps',
    'compute_lift_limit_speed', 'compute_load_factor', 'compute_stall_speed',
    # Navigation
    'point_from', 'calculate_initial_compass_bearing',
    'wind_components', 'estimate_energy_bleed_distance',
]
