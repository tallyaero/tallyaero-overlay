"""
Steep Spiral simulation module.

A steep spiral is a gliding turn wherein the pilot maintains a constant radius
around a surface-based reference point while rapidly descending. The maneuver
consists of at least three 360° turns and should conclude no lower than 1,500 ft AGL.

Reference: FAA Airplane Flying Handbook (FAA-H-8083-3C), Chapter 10

Key characteristics:
- CONSTANT GROUND TRACK (circle) around reference point - this is a ground reference maneuver
- Aircraft compensates for wind by crabbing and varying bank angle
- Bank varies with wind: steeper downwind (faster groundspeed), shallower upwind
- Maximum bank should not exceed 60°
- Constant IAS (best glide speed) throughout
- Engine at idle, descending
- At least 3 complete 360° turns
- Conclude no lower than 1,500 ft AGL
"""
import math
from geopy import Point as GeoPoint
from geopy.distance import geodesic as geo_dist

from physics import (
    compute_pressure_altitude,
    compute_true_airspeed,
    compute_load_factor,
    compute_turn_radius,
    point_from,
    calculate_initial_compass_bearing,
    G_FPS2,
    FT_PER_NM,
)

from .base import _get_best_glide_and_ratio


def _wrap_360(angle: float) -> float:
    """Normalize angle to [0, 360)."""
    return angle % 360.0


def _angle_diff_deg(a: float, b: float) -> float:
    """Compute signed difference (a - b), result in [-180, 180]."""
    diff = (a - b + 540.0) % 360.0 - 180.0
    return diff


def simulate_steep_spiral(
    reference_point: dict,
    clock_position: str,
    turn_direction: str,
    entry_altitude_ft: float,
    bank_angle_deg: float = 45.0,
    num_turns: int = 3,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    oat_c: float = 15.0,
    altimeter_inhg: float = 29.92,
    field_elev_ft: float = 0.0,
    ac: dict = None,
    weight_lb: float = None,
    timestep_sec: float = 0.5,
    min_completion_agl: float = 1500.0,
) -> tuple:
    """
    Simulate a steep spiral maneuver with constant ground track and wind compensation.

    This is a GROUND REFERENCE maneuver - the aircraft maintains a perfect circular
    ground track around the reference point regardless of wind. The aircraft compensates
    by varying heading (crab angle) and bank angle.

    Args:
        reference_point: Dict with 'lat' and 'lon' - the ground point to orbit around
        clock_position: Entry position as clock code ("12", "3", "6", "9")
        turn_direction: 'left' or 'right'
        entry_altitude_ft: Entry altitude in feet AGL
        bank_angle_deg: Base bank angle (used to calculate turn radius)
        num_turns: Number of complete 360° turns (minimum 3 per FAA)
        wind_dir_deg: Wind direction (FROM) in degrees
        wind_speed_kt: Wind speed in knots
        oat_c: Outside air temperature in Celsius
        altimeter_inhg: Altimeter setting in inches Hg
        field_elev_ft: Field elevation in feet MSL
        ac: Aircraft data dict
        weight_lb: Aircraft weight in pounds
        timestep_sec: Time step in seconds
        min_completion_agl: Minimum safe completion altitude AGL (default 1500 ft)

    Returns:
        Tuple of (path, hover_data, warnings) where:
            - path: List of [lat, lon] coordinate pairs
            - hover_data: List of dicts containing flight telemetry
            - warnings: Dict with warning flags and info
    """
    if reference_point is None:
        return [], [], {}

    dt = float(timestep_sec) if timestep_sec and timestep_sec > 0 else 0.5

    # Parse and validate inputs
    entry_altitude_ft = float(entry_altitude_ft or 5000.0)
    bank_angle_deg = float(bank_angle_deg or 45.0)
    bank_angle_deg = max(20.0, min(60.0, bank_angle_deg))
    wind_dir_deg = float(wind_dir_deg or 0.0)
    wind_speed_kt = float(wind_speed_kt or 0.0)
    oat_c = float(oat_c if oat_c is not None else 15.0)
    altimeter_inhg = float(altimeter_inhg if altimeter_inhg is not None else 29.92)
    field_elev_ft = float(field_elev_ft or 0.0)
    num_turns = max(3, int(num_turns or 3))
    min_completion_agl = float(min_completion_agl or 1500.0)

    # Turn direction: +1 for right (clockwise), -1 for left (counter-clockwise)
    turn_sign = -1.0 if str(turn_direction).lower().startswith('l') else 1.0

    # Get aircraft glide performance
    if ac is None:
        ac = {}
    bg_kias, base_glide_ratio = _get_best_glide_and_ratio(ac, None, "clean", "idle")

    # Get aircraft weight
    if weight_lb is None:
        weight_lb = ac.get("max_takeoff_weight", ac.get("gross_weight", 2300.0))
    weight_lb = float(weight_lb) if weight_lb else 2300.0

    # Compute TAS at entry altitude
    alt_msl_ft = field_elev_ft + entry_altitude_ft
    pressure_alt_ft = compute_pressure_altitude(alt_msl_ft, altimeter_inhg)
    glide_tas_knots = compute_true_airspeed(bg_kias, pressure_alt_ft, oat_c)
    glide_tas_knots = float(glide_tas_knots) if glide_tas_knots and glide_tas_knots > 1 else bg_kias
    glide_tas_fps = glide_tas_knots * 1.68781

    # Calculate turn radius from bank angle and TAS (no-wind condition)
    # R = V² / (g * tan(bank))
    bank_rad = math.radians(bank_angle_deg)
    orbit_radius_ft = (glide_tas_fps ** 2) / (G_FPS2 * math.tan(bank_rad))
    orbit_radius_nm = orbit_radius_ft / FT_PER_NM

    # Reference point
    ref_pt = GeoPoint(reference_point["lat"], reference_point["lon"])

    # Calculate entry point based on clock position
    # Clock positions relative to reference point (as viewed from above, north up)
    clock_to_bearing = {
        "12": 0.0,    # North of reference
        "3": 90.0,    # East of reference
        "6": 180.0,   # South of reference
        "9": 270.0,   # West of reference
    }
    entry_bearing = clock_to_bearing.get(str(clock_position), 0.0)
    entry_pt = point_from(ref_pt, entry_bearing, orbit_radius_nm)

    # Calculate entry heading based on clock position and turn direction
    # If entering from 12 o'clock (north) and turning left, initial heading is west (270)
    # If entering from 12 o'clock (north) and turning right, initial heading is east (90)
    if turn_sign < 0:  # Left turn
        entry_heading = _wrap_360(entry_bearing - 90.0)
    else:  # Right turn
        entry_heading = _wrap_360(entry_bearing + 90.0)

    # Wind components (wind velocity in NE frame)
    wind_to_rad = math.radians((wind_dir_deg + 180.0) % 360.0)
    wind_fps = wind_speed_kt * 1.68781
    wn_fps = wind_fps * math.cos(wind_to_rad)
    we_fps = wind_fps * math.sin(wind_to_rad)

    # Initialize warnings
    warnings = {
        'below_minimum': False,
        'ground_impact': False,
        'impact_altitude_agl': None,
        'final_altitude_agl': entry_altitude_ft,
        'suggested_min_start_alt': None,
        'altitude_per_turn': None,
        'turns_completed': 0,
        'orbit_radius_ft': round(orbit_radius_ft, 0),
        'orbit_radius_nm': round(orbit_radius_nm, 2),
    }

    path = []
    hover = []
    t = 0.0
    alt_agl = entry_altitude_ft

    # Track progress around the circle using angular position
    # Start at the entry bearing, progress around the circle
    current_angle = math.radians(entry_bearing)  # Angle from reference to aircraft
    total_angle_traveled = 0.0
    target_angle = num_turns * 2 * math.pi

    # Track altitude per turn
    altitude_at_turn_start = entry_altitude_ft
    turn_altitude_losses = []
    current_turn = 0

    def compute_descent_rate(bank_deg: float, tas_knots: float) -> float:
        """Compute descent rate in fpm based on glide ratio and bank-induced load factor."""
        n = compute_load_factor(bank_deg)
        effective_gr = base_glide_ratio / max(n, 1.0)
        effective_gr = max(2.0, effective_gr)
        tas_fpm = tas_knots * 101.269
        return tas_fpm / effective_gr

    while total_angle_traveled < target_angle:
        # Check for ground impact
        if alt_agl <= 0:
            warnings['ground_impact'] = True
            warnings['impact_altitude_agl'] = 0.0
            alt_agl = 0.0
            break

        # Current turn number (0-indexed)
        new_turn = int(total_angle_traveled / (2 * math.pi))
        if new_turn > current_turn:
            # Completed a turn
            alt_loss = altitude_at_turn_start - alt_agl
            if alt_loss > 0:
                turn_altitude_losses.append(alt_loss)
            altitude_at_turn_start = alt_agl
            current_turn = new_turn

        # Current position on the circle (ground track is constant)
        pos_lat = ref_pt.latitude + (orbit_radius_ft / 364567.2) * math.cos(current_angle)
        pos_lon = ref_pt.longitude + (orbit_radius_ft / (364567.2 * math.cos(math.radians(ref_pt.latitude)))) * math.sin(current_angle)

        # Ground track direction (tangent to circle)
        # For left turn (CCW when viewed from above): track is perpendicular to radius, 90° CCW
        # For right turn (CW): track is perpendicular to radius, 90° CW
        track_deg = _wrap_360(math.degrees(current_angle) + turn_sign * 90.0)
        track_rad = math.radians(track_deg)

        # To maintain constant ground track, we need to calculate required heading and bank
        # Ground velocity must be tangent to circle at the correct groundspeed

        # Required groundspeed to maintain position on circle
        # For constant angular rate, GS = R * omega, where omega = angular velocity
        # But we're constrained by TAS, so we solve for the heading that gives us
        # the correct ground track direction

        # Wind triangle: Ground velocity = Air velocity + Wind velocity
        # We know: track direction, TAS magnitude, wind velocity
        # Solve for: heading, groundspeed, bank angle

        # Ground track unit vector
        track_n = math.cos(track_rad)
        track_e = math.sin(track_rad)

        # Wind component along track (positive = tailwind)
        wind_along_track = wn_fps * track_n + we_fps * track_e

        # Wind component across track (positive = wind from left pushing right)
        wind_across_track = -wn_fps * track_e + we_fps * track_n

        # To maintain track, aircraft must crab into crosswind
        # sin(crab) = -wind_across / TAS
        cross_ratio = wind_across_track / max(glide_tas_fps, 50.0)
        cross_ratio = max(-0.95, min(0.95, cross_ratio))  # Limit for asin
        crab_rad = math.asin(-cross_ratio)
        crab_deg = math.degrees(crab_rad)

        # Aircraft heading
        hdg_deg = _wrap_360(track_deg + crab_deg)
        hdg_rad = math.radians(hdg_deg)

        # Groundspeed along track
        along_air = glide_tas_fps * math.cos(crab_rad)
        gs_fps = along_air + wind_along_track
        gs_fps = max(10.0, gs_fps)  # Minimum groundspeed
        gs_kt = gs_fps / 1.68781

        # Required bank angle to maintain turn at this groundspeed
        # Turn rate = V / R, and turn rate = g * tan(bank) / V
        # So: g * tan(bank) / TAS = GS / R (angular rate from groundspeed)
        # But we need: bank such that aircraft follows the circular ground track

        # For ground reference maneuver, the key is that the GROUND track is circular
        # The required centripetal acceleration (in ground frame) is: a = GS² / R
        # This must come from the horizontal component of lift
        # Bank angle: tan(bank) = a / g = GS² / (R * g)

        required_centripetal = (gs_fps ** 2) / orbit_radius_ft
        tan_bank = required_centripetal / G_FPS2
        actual_bank_deg = math.degrees(math.atan(tan_bank))
        actual_bank_deg = max(15.0, min(60.0, actual_bank_deg))  # Safety limits

        # Compute descent rate at this bank angle
        descent_fpm = compute_descent_rate(actual_bank_deg, glide_tas_knots)

        # Drift angle (difference between heading and track)
        drift_deg = _angle_diff_deg(track_deg, hdg_deg)

        # Record point (apply turn_sign to bank for L/R display)
        load_factor = 1.0 / math.cos(math.radians(actual_bank_deg)) if abs(actual_bank_deg) < 89.9 else None
        hover.append({
            "time": round(t, 2),
            "alt": round(alt_agl, 1),
            "tas": round(glide_tas_knots, 1),
            "ias": round(bg_kias, 1),
            "gs": round(gs_kt, 1),
            "aob": round(turn_sign * actual_bank_deg, 1),
            "load_factor": round(load_factor, 2) if load_factor is not None else None,
            "vs": round(-descent_fpm, 0),
            "track": round(track_deg, 1),
            "heading": round(hdg_deg, 1),
            "drift": round(drift_deg, 1),
            "segment": f"turn_{current_turn + 1}",
            "turn_number": current_turn + 1,
            "turn_progress": round(math.degrees(total_angle_traveled % (2 * math.pi)), 1),
        })
        path.append([pos_lat, pos_lon])

        # Advance around circle based on groundspeed
        # Angular velocity = GS / R
        angular_velocity = gs_fps / orbit_radius_ft  # rad/s
        d_angle = angular_velocity * dt

        # Update position (move in turn direction)
        current_angle += turn_sign * d_angle
        total_angle_traveled += d_angle

        # Update altitude
        alt_agl -= (descent_fpm / 60.0) * dt

        # Advance time
        t += dt

        # Safety limit
        if t > 600:  # 10 minutes max
            break

    # Record final point
    if alt_agl > 0:
        final_pos_lat = ref_pt.latitude + (orbit_radius_ft / 364567.2) * math.cos(current_angle)
        final_pos_lon = ref_pt.longitude + (orbit_radius_ft / (364567.2 * math.cos(math.radians(ref_pt.latitude)))) * math.sin(current_angle)
        track_deg = _wrap_360(math.degrees(current_angle) + turn_sign * 90.0)

        load_factor2 = 1.0 / math.cos(math.radians(actual_bank_deg)) if abs(actual_bank_deg) < 89.9 else None
        hover.append({
            "time": round(t, 2),
            "alt": round(alt_agl, 1),
            "tas": round(glide_tas_knots, 1),
            "ias": round(bg_kias, 1),
            "gs": round(gs_kt, 1),
            "aob": round(turn_sign * actual_bank_deg, 1),  # Apply turn_sign for L/R display
            "load_factor": round(load_factor2, 2) if load_factor2 is not None else None,
            "vs": round(-descent_fpm, 0),
            "track": round(track_deg, 1),
            "heading": round(hdg_deg, 1),
            "drift": round(drift_deg, 1),
            "segment": f"turn_{current_turn + 1}",
            "turn_number": current_turn + 1,
            "turn_progress": round(math.degrees(total_angle_traveled % (2 * math.pi)), 1),
        })
        path.append([final_pos_lat, final_pos_lon])

    # Calculate warnings and statistics
    final_alt = max(0.0, alt_agl)
    warnings['final_altitude_agl'] = round(final_alt, 0)
    warnings['turns_completed'] = min(current_turn + 1, num_turns)

    if final_alt < min_completion_agl:
        warnings['below_minimum'] = True

    # Average altitude loss per turn
    if turn_altitude_losses:
        avg_alt_per_turn = sum(turn_altitude_losses) / len(turn_altitude_losses)
    else:
        total_alt_loss = entry_altitude_ft - final_alt
        avg_alt_per_turn = total_alt_loss / max(1, num_turns)

    warnings['altitude_per_turn'] = round(avg_alt_per_turn, 0)

    # Suggested minimum starting altitude
    safety_margin = 200.0
    suggested_min = (num_turns * avg_alt_per_turn) + min_completion_agl + safety_margin
    warnings['suggested_min_start_alt'] = round(suggested_min, 0)

    # Include entry point info for the callback
    warnings['entry_point'] = {'lat': entry_pt.latitude, 'lon': entry_pt.longitude}
    warnings['entry_heading'] = round(entry_heading, 0)

    return path, hover, warnings
