"""
Simulation module for flight maneuver simulations.
"""

from .base import (
    _canon_flap_config, _canon_prop_config,
    _ref_weight_lb, _runtime_total_weight_lb,
    _weight_adjust_speed_kias, _best_glide_speed_kias,
    _get_best_glide_and_ratio
)

from .steep_turn import simulate_steep_turn

from .chandelle import simulate_chandelle

from .lazy_eight import simulate_lazy_eight

from .steep_spiral import simulate_steep_spiral

from .s_turn import simulate_s_turn

from .glide_path import (
    simulate_glide_path_to_target,
    find_required_aob_for_arc_fit
)

from .engine_out import (
    simulate_engineout_glide,
    simulate_tight_overhead_orbit
)

from .impossible_turn import (
    simulate_impossible_turn,
    _run_impossible_turn_once
)

from .turns_around_point import simulate_turns_around_point

from .rectangular_course import simulate_rectangular_course

from .eights_on_pylons import simulate_eights_on_pylons, compute_pivotal_altitude

__all__ = [
    # Base utilities
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
]
