"""
Aviation utility functions module.

This module has been refactored into a modular structure.
All functions are re-exported here for backward compatibility.

New code should import from the specific modules:
    - physics/ - Physical constants and calculations
    - simulation/ - Flight simulation engines
    - rendering/ - Map visualization helpers
"""

# Re-export from physics module
from physics import (
    # Constants
    g, G_FPS2, R, T_sl, P_sl, rho_sl,
    FT_PER_NM, FT_PER_M,
    OVERHEAD_THRESH_FT, FINAL_MIN_DIST_NM, FINAL_MAX_DIST_NM,
    FINAL_CROSSING_HEIGHT_FT, FINAL_ALIGN_TOL_DEG, DEFAULT_ALIGN_WINDOW_DEG,

    # Conversions
    knots_to_fps, fps_to_knots, fpm_to_fps,

    # Atmosphere
    compute_density_altitude, compute_pressure_altitude,
    compute_air_density, adjust_glide_ratio_for_density,

    # Aerodynamics
    compute_true_airspeed, compute_turn_radius, compute_required_bank,
    compute_glide_ratio, compute_descent_angle_deg, compute_Ps,
    compute_lift_limit_speed, compute_load_factor, compute_stall_speed,

    # Navigation
    point_from, calculate_initial_compass_bearing,
    wind_components, estimate_energy_bleed_distance,
    _wrap_360, _angle_diff_deg, _bearing_to_unit_ne,
    _cross_track_distance_ft, _heading_from_track_components,
    _wind_components_from_dir, _local_xy_ft, _cross_track_to_centerline_ft,
)

# Re-export from simulation module
from simulation import (
    # Base utilities
    _canon_flap_config, _canon_prop_config,
    _ref_weight_lb, _runtime_total_weight_lb,
    _weight_adjust_speed_kias, _best_glide_speed_kias,
    _get_best_glide_and_ratio,

    # Simulations
    simulate_steep_turn,
    simulate_chandelle,
    simulate_lazy_eight,
    simulate_steep_spiral,
    simulate_s_turn,
    simulate_glide_path_to_target,
    find_required_aob_for_arc_fit,
    simulate_engineout_glide,
    simulate_tight_overhead_orbit,
    simulate_impossible_turn,
    simulate_turns_around_point,
    simulate_rectangular_course,
    simulate_eights_on_pylons,
    compute_pivotal_altitude,
)

# Re-export from rendering module
from rendering import render_hover_polyline


# Legacy aliases for maximum backward compatibility
# These ensure any import patterns from the old utility.py continue to work

__all__ = [
    # Constants
    'g', 'G_FPS2', 'R', 'T_sl', 'P_sl', 'rho_sl',
    'FT_PER_NM', 'FT_PER_M',
    'OVERHEAD_THRESH_FT', 'FINAL_MIN_DIST_NM', 'FINAL_MAX_DIST_NM',
    'FINAL_CROSSING_HEIGHT_FT', 'FINAL_ALIGN_TOL_DEG', 'DEFAULT_ALIGN_WINDOW_DEG',

    # Conversions
    'knots_to_fps', 'fps_to_knots', 'fpm_to_fps',

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

    # Simulation base
    '_canon_flap_config', '_canon_prop_config',
    '_ref_weight_lb', '_runtime_total_weight_lb',
    '_weight_adjust_speed_kias', '_best_glide_speed_kias',
    '_get_best_glide_and_ratio',

    # Simulations
    'simulate_steep_turn',
    'simulate_chandelle',
    'simulate_lazy_eight',
    'simulate_steep_spiral',
    'simulate_s_turn',
    'simulate_glide_path_to_target',
    'find_required_aob_for_arc_fit',
    'simulate_engineout_glide',
    'simulate_tight_overhead_orbit',
    'simulate_impossible_turn',
    'simulate_turns_around_point',
    'simulate_rectangular_course',
    'simulate_eights_on_pylons',
    'compute_pivotal_altitude',

    # Rendering
    'render_hover_polyline',
]
