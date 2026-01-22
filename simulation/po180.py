"""
Power-Off 180 Accuracy Approach simulation module.

Energy-based model with automatic slip calculation for the commercial pilot
accuracy approach maneuver. Simulates glide from abeam position at pattern
altitude to touchdown with ACS standard: -0/+200 ft.

Reference: FAA Airplane Flying Handbook (FAA-H-8083-3C), Chapter 8
           FAA Commercial Pilot ACS (FAA-S-ACS-7)
"""
import math
from geopy import Point as GeoPoint
from geopy.distance import geodesic as geo_dist

from physics import (
    compute_pressure_altitude,
    compute_air_density,
    compute_true_airspeed,
    compute_glide_ratio,
    adjust_glide_ratio_for_density,
    compute_load_factor,
    knots_to_fps,
    g,
    FT_PER_NM,
    point_from,
    calculate_initial_compass_bearing,
)

from .base import _get_best_glide_and_ratio, _canon_flap_config, _canon_prop_config


def _wrap_360(angle: float) -> float:
    """Normalize angle to [0, 360)."""
    return angle % 360.0


def _angle_diff(a: float, b: float) -> float:
    """Compute signed difference (a - b), result in [-180, 180]."""
    return ((a - b + 540.0) % 360.0) - 180.0


def _calculate_wind_correction(
    track_deg: float,
    tas_knots: float,
    wind_dir_deg: float,
    wind_speed_kt: float,
) -> tuple:
    """
    Calculate wind triangle solution.

    Returns:
        (groundspeed_kt, heading_deg, drift_deg)
    """
    if wind_speed_kt < 0.1:
        return tas_knots, track_deg, 0.0

    # Wind is FROM direction, convert to TO direction
    wind_to_rad = math.radians((wind_dir_deg + 180.0) % 360.0)
    track_rad = math.radians(track_deg)

    # Wind components in track frame
    wind_along = wind_speed_kt * math.cos(wind_to_rad - track_rad)
    wind_cross = wind_speed_kt * math.sin(wind_to_rad - track_rad)

    # Crab angle to correct for crosswind
    cross_ratio = min(0.99, max(-0.99, -wind_cross / tas_knots))
    crab_rad = math.asin(cross_ratio)
    drift_deg = math.degrees(crab_rad)

    # Heading to maintain track
    heading_deg = _wrap_360(track_deg + drift_deg)

    # Groundspeed
    along_component = tas_knots * math.cos(crab_rad)
    gs_knots = max(5.0, along_component + wind_along)

    return gs_knots, heading_deg, drift_deg


def _calculate_slip_requirement(
    altitude_available_ft: float,
    distance_to_cover_ft: float,
    base_glide_ratio: float,
    max_slip_effectiveness: float = 0.5,
) -> dict:
    """
    Calculate slip needed to dissipate excess energy.
    """
    if altitude_available_ft <= 0 or distance_to_cover_ft <= 0:
        return {
            'slip_needed': False,
            'slip_intensity': 0.0,
            'effective_glide_ratio': base_glide_ratio,
            'altitude_excess_ft': 0.0,
        }

    required_gr = distance_to_cover_ft / altitude_available_ft

    if required_gr >= base_glide_ratio:
        return {
            'slip_needed': False,
            'slip_intensity': 0.0,
            'effective_glide_ratio': base_glide_ratio,
            'altitude_excess_ft': altitude_available_ft - (distance_to_cover_ft / base_glide_ratio),
        }

    slip_intensity = (base_glide_ratio - required_gr) / (base_glide_ratio * max_slip_effectiveness)
    slip_intensity = max(0.0, min(1.0, slip_intensity))

    effective_gr = base_glide_ratio * (1.0 - slip_intensity * max_slip_effectiveness)
    altitude_excess = altitude_available_ft - (distance_to_cover_ft / base_glide_ratio)

    return {
        'slip_needed': slip_intensity > 0.01,
        'slip_intensity': slip_intensity,
        'effective_glide_ratio': effective_gr,
        'altitude_excess_ft': altitude_excess,
    }


def simulate_power_off_180(
    runway_threshold: dict,
    runway_heading_deg: float,
    runway_length_ft: float,
    abeam_distance_nm: float,
    pattern_direction: str,
    ac: dict,
    weight_lbs: float,
    flap_config: str,
    prop_config: str,
    oat_c: float,
    altimeter_inhg: float,
    wind_dir_deg: float,
    wind_speed_kt: float,
    field_elev_ft: float,
    pattern_altitude_agl: float = 1000.0,
    timestep_sec: float = 0.5,
) -> tuple:
    """
    Simulate a Power-Off 180 accuracy approach.

    The simulation builds geometry backwards from touchdown to ensure the path
    ends at the correct point, then flies forward from downwind to touchdown.

    Path order: Downwind Entry → Downwind → Base Turn (180°) → Final → Touchdown
    """
    if runway_threshold is None:
        return [], [], {'success': False, 'error': 'No runway threshold'}

    flap_config = _canon_flap_config(flap_config)
    prop_config = _canon_prop_config(prop_config)

    # Aircraft performance
    best_glide_kias, base_glide_ratio = _get_best_glide_and_ratio(ac, None, flap_config, prop_config)
    gear_type = ac.get("gear_type", "fixed")

    # Environment
    alt_msl_ft = field_elev_ft + pattern_altitude_agl
    pressure_alt_ft = compute_pressure_altitude(alt_msl_ft, altimeter_inhg)
    rho = compute_air_density(pressure_alt_ft, oat_c)

    # Glide ratio with config effects
    straight_gr = compute_glide_ratio(base_glide_ratio, flap_config, gear_type, prop_config)
    straight_gr = adjust_glide_ratio_for_density(straight_gr, rho)
    straight_gr = max(3.0, min(straight_gr, 25.0))

    # TAS
    tas_knots = compute_true_airspeed(best_glide_kias, pressure_alt_ft, oat_c)
    tas_fps = knots_to_fps(tas_knots)

    # Pattern geometry
    # For LEFT pattern: aircraft is on LEFT side of runway (looking down runway heading)
    # For RIGHT pattern: aircraft is on RIGHT side of runway
    is_left_pattern = pattern_direction.lower().startswith('l')
    turn_direction = -1.0 if is_left_pattern else 1.0  # -1 = left turn, +1 = right turn

    downwind_heading = _wrap_360(runway_heading_deg + 180.0)
    final_heading = runway_heading_deg

    # Abeam distance
    abeam_distance_ft = abeam_distance_nm * FT_PER_NM

    # =========================================================================
    # GEOMETRY CALCULATION (working backwards from touchdown)
    # =========================================================================

    # Turn radius: for 180° turn, lateral displacement = 2R
    # To move from pattern offset to centerline: 2R = abeam_distance
    ideal_R = abeam_distance_ft / 2.0

    # Bank angle for this radius
    tan_bank = (tas_fps ** 2) / (g * ideal_R)
    bank_from_geometry = math.degrees(math.atan(tan_bank))
    bank_deg = max(5.0, min(45.0, bank_from_geometry))

    # Actual turn radius with clamped bank
    bank_rad = math.radians(bank_deg)
    R_ft = (tas_fps ** 2) / (g * math.tan(bank_rad))

    # Turn glide ratio (reduced due to load factor)
    n_turn = compute_load_factor(bank_deg)
    turn_gr = straight_gr / max(n_turn, 1.0)
    turn_gr = max(2.0, turn_gr)

    # Arc length for 180° turn
    arc_length_ft = math.pi * R_ft

    # Key points (using local coordinate system then converting to lat/lon)
    # Origin = touchdown point
    # X = perpendicular to runway (positive = right side of runway when looking down heading)
    # Y = along runway (positive = direction of runway heading)

    touchdown_pt = GeoPoint(runway_threshold['lat'], runway_threshold['lon'])

    # Pattern side offset direction
    # Left pattern = aircraft on left = negative X
    # Right pattern = aircraft on right = positive X
    pattern_side = -1.0 if is_left_pattern else 1.0

    # =========================================================================
    # ENERGY-BASED SEGMENT CALCULATION
    # =========================================================================
    # Key insight: In this geometry, the turn starts and ends at the same Y position.
    # So: downwind_distance = downwind_before_abeam + final_distance
    # Total altitude = downwind/GR_straight + arc/GR_turn + final/GR_straight
    #                = (downwind_before_abeam + final)/GR_straight + arc/GR_turn + final/GR_straight
    #                = downwind_before_abeam/GR_straight + 2*final/GR_straight + arc/GR_turn
    # Solving for final:
    # final = (h0 - downwind_before_abeam/GR_straight - arc/GR_turn) * GR_straight / 2

    downwind_before_abeam_ft = 300.0  # Entry distance before abeam point

    alt_for_entry = downwind_before_abeam_ft / straight_gr
    alt_for_turn = arc_length_ft / turn_gr

    # Remaining altitude for downwind_past_abeam + final (which are equal in this geometry)
    alt_remaining = pattern_altitude_agl - alt_for_entry - alt_for_turn

    # Each of downwind_past_abeam and final gets half the remaining altitude
    if alt_remaining > 0:
        final_distance_ft = (alt_remaining / 2.0) * straight_gr
    else:
        # Not enough altitude - set minimum final and warn
        final_distance_ft = 300.0

    final_distance_ft = max(300.0, min(final_distance_ft, 1500.0))  # Clamp to reasonable range

    # Downwind past abeam equals final distance (due to geometry)
    downwind_past_abeam_ft = final_distance_ft
    total_downwind_ft = downwind_before_abeam_ft + downwind_past_abeam_ft

    # Now calculate the actual waypoints
    # Work backwards from touchdown

    # 1. Touchdown point (origin)
    td_x, td_y = 0.0, 0.0

    # 2. Turn end point (start of final approach)
    # Final approach is along runway heading, so turn end is straight back from touchdown
    turn_end_x = 0.0
    turn_end_y = -final_distance_ft  # Negative = behind touchdown

    # 3. Turn center
    # For left pattern with left turn: center is to the RIGHT of final approach track
    # For right pattern with right turn: center is to the LEFT of final approach track
    # At turn end, the center is perpendicular to the track
    turn_center_x = turn_end_x + pattern_side * R_ft  # Opposite side from pattern
    turn_center_y = turn_end_y

    # 4. Turn start point (end of downwind, start of turn)
    # 180° around the circle from turn end
    turn_start_x = turn_center_x + pattern_side * R_ft  # Same side as pattern
    turn_start_y = turn_center_y  # Same Y as turn end (180° turn has no Y displacement)

    # Note: turn_start_x should equal pattern offset if geometry is correct
    # turn_start_x = pattern_side * R_ft + pattern_side * R_ft = pattern_side * 2R
    # This should equal pattern_side * abeam_distance if 2R = abeam_distance

    # 5. Abeam point (directly beside touchdown at pattern offset)
    abeam_x = pattern_side * abeam_distance_ft
    abeam_y = 0.0  # Same Y as touchdown

    # 6. Downwind start (before abeam)
    # Downwind track is opposite runway heading, so positive Y is "before" in downwind direction
    downwind_start_x = abeam_x  # Same lateral offset
    downwind_start_y = downwind_before_abeam_ft  # Ahead of abeam in downwind direction

    # Calculate actual downwind distance from start to turn
    # Turn start Y = turn_end_y = -final_distance_ft
    # So downwind travels from Y = downwind_before_abeam_ft to Y = -final_distance_ft
    actual_downwind_dist = downwind_start_y - turn_start_y

    # Helper function to convert local XY to lat/lon
    def xy_to_latlon(x_ft, y_ft):
        """Convert local XY (ft) to lat/lon relative to touchdown."""
        # Y is along runway heading, X is perpendicular
        # Bearing for +Y is runway_heading
        # Bearing for +X is runway_heading + 90

        if abs(x_ft) < 1 and abs(y_ft) < 1:
            return touchdown_pt.latitude, touchdown_pt.longitude

        # Convert to polar (distance and bearing from touchdown)
        dist_ft = math.sqrt(x_ft**2 + y_ft**2)
        angle_from_runway = math.degrees(math.atan2(x_ft, y_ft))  # atan2(x,y) for bearing
        bearing = _wrap_360(runway_heading_deg + angle_from_runway)

        pt = geo_dist(feet=dist_ft).destination(touchdown_pt, bearing)
        return pt.latitude, pt.longitude

    # Convert key points to lat/lon
    downwind_start_latlon = xy_to_latlon(downwind_start_x, downwind_start_y)
    abeam_latlon = xy_to_latlon(abeam_x, abeam_y)
    turn_start_latlon = xy_to_latlon(turn_start_x, turn_start_y)
    turn_center_latlon = xy_to_latlon(turn_center_x, turn_center_y)
    turn_end_latlon = xy_to_latlon(turn_end_x, turn_end_y)

    # =========================================================================
    # SIMULATION (flying forward from downwind start to touchdown)
    # =========================================================================

    path = []
    hover = []

    # Initial state
    lat, lon = downwind_start_latlon
    alt_ft = pattern_altitude_agl
    time_s = 0.0
    dt = timestep_sec

    # Segment tracking
    segment = "downwind"
    segment_distance_ft = 0.0

    # For turn: track angle around circle (0 to 180 degrees)
    turn_progress_deg = 0.0

    # Slip tracking
    slip_active = False
    slip_intensity = 0.0
    slip_start_time = None
    slip_start_alt = None

    # Track actual bank angles during turn
    turn_bank_angles = []

    # Calculate slip requirement for final
    slip_info = _calculate_slip_requirement(
        altitude_available_ft=pattern_altitude_agl - (actual_downwind_dist / straight_gr) - (arc_length_ft / turn_gr),
        distance_to_cover_ft=final_distance_ft,
        base_glide_ratio=straight_gr,
    )

    max_steps = 5000

    for step in range(max_steps):
        # Current position in local XY
        current_latlon = (lat, lon)

        # Determine segment and track
        if segment == "downwind":
            track_deg = downwind_heading
            current_gr = straight_gr
            current_bank = 0.0

        elif segment == "turn":
            # Track changes continuously through turn
            # For left turn: track goes from downwind_heading toward final_heading (decreasing)
            # For right turn: track goes from downwind_heading toward final_heading (increasing)
            if is_left_pattern:
                track_deg = _wrap_360(downwind_heading - turn_progress_deg)
            else:
                track_deg = _wrap_360(downwind_heading + turn_progress_deg)

            # Bank angle varies with groundspeed to maintain constant radius ground track
            # Higher GS (downwind) = steeper bank, Lower GS (upwind) = shallower bank
            # Formula: tan(bank) = GS² / (R × g)
            gs_for_bank, _, _ = _calculate_wind_correction(track_deg, tas_knots, wind_dir_deg, wind_speed_kt)
            gs_fps_for_bank = knots_to_fps(gs_for_bank)
            required_centripetal = (gs_fps_for_bank ** 2) / R_ft
            tan_bank_required = required_centripetal / g
            current_bank_mag = math.degrees(math.atan(tan_bank_required))
            current_bank_mag = max(5.0, min(60.0, current_bank_mag))  # Safety limits
            current_bank = current_bank_mag * turn_direction

            # Glide ratio varies with actual bank (load factor changes)
            n_actual = 1.0 / math.cos(math.radians(current_bank_mag))
            current_gr = straight_gr / max(n_actual, 1.0)
            current_gr = max(2.0, current_gr)

            # Track bank angles for reporting
            turn_bank_angles.append(current_bank_mag)

        else:  # final
            track_deg = final_heading
            if slip_active:
                current_gr = slip_info['effective_glide_ratio']
            else:
                current_gr = straight_gr
            current_bank = 0.0

        # Wind correction
        gs_knots, heading_deg, drift_deg = _calculate_wind_correction(
            track_deg, tas_knots, wind_dir_deg, wind_speed_kt
        )
        gs_fps = knots_to_fps(gs_knots)

        # Distance and altitude step
        ds_ft = tas_fps * dt
        dh_ft = ds_ft / current_gr
        alt_ft = max(0.0, alt_ft - dh_ft)

        vs_fpm = -(dh_ft / dt) * 60.0 if dt > 0.001 else 0.0

        # Distance to touchdown
        dist_to_td_ft = geo_dist(current_latlon, (touchdown_pt.latitude, touchdown_pt.longitude)).feet

        # Record point
        path.append([lat, lon])

        # Determine slip percentage for hover display
        # Use actual slip_intensity if active, otherwise use slip_info when on final
        if slip_active:
            hover_slip_pct = round(slip_intensity * 100, 0)
        elif segment == "final" and slip_info['slip_needed']:
            hover_slip_pct = round(slip_info['slip_intensity'] * 100, 0)
        else:
            hover_slip_pct = 0

        hover.append({
            'time': round(time_s, 2),
            'segment': segment,
            'alt': round(alt_ft, 1),
            'ias': round(best_glide_kias, 1),
            'tas': round(tas_knots, 1),
            'gs': round(gs_knots, 1),
            'vs': round(vs_fpm, 0),
            'heading': round(heading_deg, 1),
            'track': round(track_deg, 1),
            'drift': round(drift_deg, 1),
            'aob': round(current_bank, 1),
            'slip_active': slip_active or (segment == "final" and slip_info['slip_needed']),
            'slip_intensity': hover_slip_pct,
            'slip_pct': hover_slip_pct,
            'glide_ratio': round(current_gr, 1),
            'distance_to_touchdown_ft': round(dist_to_td_ft, 0),
        })

        # Update position based on segment
        if segment == "downwind":
            # Move along downwind track
            ds_nm = ds_ft / FT_PER_NM
            new_pt = point_from(GeoPoint(lat, lon), track_deg, ds_nm)
            lat, lon = new_pt.latitude, new_pt.longitude
            segment_distance_ft += ds_ft

            # Check for turn start
            dist_to_turn_start = geo_dist(
                (lat, lon), turn_start_latlon
            ).feet

            if dist_to_turn_start < ds_ft * 1.5 or segment_distance_ft >= actual_downwind_dist:
                segment = "turn"
                segment_distance_ft = 0.0
                turn_progress_deg = 0.0
                # Smooth transition - don't snap, just continue from current position

        elif segment == "turn":
            # Move along arc - calculate position on circle
            d_angle = math.degrees(ds_ft / R_ft)
            turn_progress_deg += d_angle

            # Calculate position on arc relative to turn center
            # Start angle: direction from center to turn_start
            start_angle_local = math.atan2(
                turn_start_x - turn_center_x,
                turn_start_y - turn_center_y
            )

            # Current angle (rotating in turn direction)
            if is_left_pattern:
                current_angle = start_angle_local - math.radians(turn_progress_deg)
            else:
                current_angle = start_angle_local + math.radians(turn_progress_deg)

            # Position in local coordinates
            pos_x = turn_center_x + R_ft * math.sin(current_angle)
            pos_y = turn_center_y + R_ft * math.cos(current_angle)

            lat, lon = xy_to_latlon(pos_x, pos_y)

            # Check for turn complete
            if turn_progress_deg >= 180.0:
                segment = "final"
                segment_distance_ft = 0.0

                # Recalculate slip based on actual altitude at final start
                actual_slip = _calculate_slip_requirement(
                    altitude_available_ft=alt_ft,
                    distance_to_cover_ft=final_distance_ft,
                    base_glide_ratio=straight_gr,
                )

                if actual_slip['slip_needed']:
                    slip_active = True
                    slip_start_time = time_s
                    slip_start_alt = alt_ft
                    slip_intensity = actual_slip['slip_intensity']

        else:  # final
            # Move along final approach track
            ds_nm = ds_ft / FT_PER_NM
            new_pt = point_from(GeoPoint(lat, lon), track_deg, ds_nm)
            lat, lon = new_pt.latitude, new_pt.longitude
            segment_distance_ft += ds_ft

        time_s += dt

        # Check for touchdown
        if dist_to_td_ft <= 30.0 or alt_ft <= 0.0:
            break

        if time_s > 300:
            break

    # =========================================================================
    # RESULTS
    # =========================================================================

    final_lat, final_lon = lat, lon
    final_dist = geo_dist((final_lat, final_lon), (touchdown_pt.latitude, touchdown_pt.longitude)).feet

    # Determine short or long
    bearing_to_td = calculate_initial_compass_bearing(GeoPoint(final_lat, final_lon), touchdown_pt)
    bearing_diff = abs(_angle_diff(bearing_to_td, final_heading))

    if alt_ft > 0 and final_dist <= 30:
        touchdown_error_ft = 0.0
    elif bearing_diff < 90:
        touchdown_error_ft = -final_dist  # Short
    else:
        touchdown_error_ft = final_dist  # Long

    # ACS: -0/+200 ft
    success = touchdown_error_ft >= -10 and touchdown_error_ft <= 200

    # Add touchdown point
    path.append([touchdown_pt.latitude, touchdown_pt.longitude])
    hover.append({
        'time': round(time_s + dt, 2),
        'segment': 'touchdown',
        'alt': 0.0,
        'ias': round(best_glide_kias, 1),
        'tas': round(tas_knots, 1),
        'gs': round(gs_knots, 1),
        'vs': round(vs_fpm, 0),
        'heading': round(heading_deg, 1),
        'track': round(final_heading, 1),
        'drift': round(drift_deg, 1),
        'aob': 0.0,
        'slip_active': False,
        'slip_intensity': 0,
        'slip_pct': 0,
        'glide_ratio': round(straight_gr, 1),
        'distance_to_touchdown_ft': 0,
    })

    # Wind on final
    wind_to_rad = math.radians((wind_dir_deg + 180.0) % 360.0)
    final_rad = math.radians(final_heading)
    headwind_kt = wind_speed_kt * math.cos(wind_to_rad - final_rad)
    crosswind_kt = wind_speed_kt * math.sin(wind_to_rad - final_rad)

    results = {
        'success': success,
        'touchdown_error_ft': round(touchdown_error_ft, 0),
        'impact_point': [final_lat, final_lon] if alt_ft <= 0 else None,

        'slip_used': slip_active or slip_info['slip_needed'],
        'slip_intensity_pct': round(slip_intensity * 100, 0),
        'slip_start_time_sec': slip_start_time,
        'slip_start_alt_ft': round(slip_start_alt, 0) if slip_start_alt else None,

        'best_glide_kias': round(best_glide_kias, 0),
        'bank_min_deg': round(min(turn_bank_angles), 1) if turn_bank_angles else round(bank_deg, 1),
        'bank_max_deg': round(max(turn_bank_angles), 1) if turn_bank_angles else round(bank_deg, 1),
        'turn_radius_ft': round(R_ft, 0),
        'base_glide_ratio': round(straight_gr, 1),
        'turn_glide_ratio': round(turn_gr, 1),
        'effective_glide_ratio': round(slip_info['effective_glide_ratio'], 1) if slip_info['slip_needed'] else round(straight_gr, 1),
        'total_time_sec': round(time_s, 1),

        'downwind_distance_ft': round(actual_downwind_dist, 0),
        'arc_length_ft': round(arc_length_ft, 0),
        'final_distance_ft': round(final_distance_ft, 0),

        'headwind_on_final_kt': round(headwind_kt, 0),
        'crosswind_on_final_kt': round(abs(crosswind_kt), 0),
        'crosswind_direction': 'left' if crosswind_kt > 0 else 'right' if crosswind_kt < 0 else 'none',

        'pattern_altitude_ft': round(pattern_altitude_agl, 0),
        'abeam_distance_nm': round(abeam_distance_nm, 2),
    }

    return path, hover, results


# Legacy wrapper for engine_out.py
def simulate_glide_path_to_target(
    start_point, start_heading, touchdown_point, touchdown_heading,
    ac, engine_option, weight_lbs, flap_config, prop_config,
    oat_c, altimeter_inhg, wind_dir, wind_speed, start_ias_kias,
    altitude_agl, pattern_dir, selected_airport_elev_ft,
    max_bank_deg=45, timestep_sec=0.5,
):
    """Legacy wrapper for engine_out.py compatibility."""
    if start_point is None or touchdown_point is None:
        return [], [], None

    runway_threshold = {
        'lat': touchdown_point.latitude,
        'lon': touchdown_point.longitude,
    }

    abeam_dist_ft = geo_dist(
        (start_point.latitude, start_point.longitude),
        (touchdown_point.latitude, touchdown_point.longitude)
    ).feet
    abeam_distance_nm = abeam_dist_ft / FT_PER_NM

    path, hover, results = simulate_power_off_180(
        runway_threshold=runway_threshold,
        runway_heading_deg=float(touchdown_heading),
        runway_length_ft=5000.0,
        abeam_distance_nm=min(1.5, max(0.3, abeam_distance_nm)),
        pattern_direction=pattern_dir,
        ac=ac,
        weight_lbs=float(weight_lbs) if weight_lbs else 2500.0,
        flap_config=flap_config,
        prop_config=prop_config,
        oat_c=float(oat_c),
        altimeter_inhg=float(altimeter_inhg),
        wind_dir_deg=float(wind_dir) if wind_dir else 0.0,
        wind_speed_kt=float(wind_speed) if wind_speed else 0.0,
        field_elev_ft=float(selected_airport_elev_ft) if selected_airport_elev_ft else 0.0,
        pattern_altitude_agl=float(altitude_agl) if altitude_agl else 1000.0,
        timestep_sec=timestep_sec,
    )

    return path, hover, results.get('impact_point')
