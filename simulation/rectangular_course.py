"""
Rectangular Course simulation module.

The path IS the ideal geometry - a perfect rectangle on the ground with rounded corners.
At each point, we calculate what bank/heading/crab is REQUIRED to fly that perfect track.

Two clicks define the downwind leg. The rectangle extends perpendicular by lateral_offset.
Entry is on 45° to the midpoint of downwind. Maneuver ends back at the midpoint.

Reference: FAA Airplane Flying Handbook (FAA-H-8083-3C), Chapter 7
"""
import math

from physics import (
    compute_pressure_altitude,
    compute_true_airspeed,
    G_FPS2,
    FT_PER_NM,
)

from .base import _ref_weight_lb


def _wrap_360(angle: float) -> float:
    """Normalize angle to [0, 360)."""
    return angle % 360.0


def _format_crab(crab_deg: float) -> str:
    """Format crab angle as string."""
    if abs(crab_deg) < 0.1:
        return "0°"
    elif crab_deg > 0:
        return f"right {abs(crab_deg):.1f}°"
    else:
        return f"left {abs(crab_deg):.1f}°"


def simulate_rectangular_course(
    dw_start: dict,
    dw_end: dict,
    lateral_offset_nm: float = 0.75,
    pattern_direction: str = "left",
    altitude_ft: float = 800.0,
    ias_knots: float = 95.0,
    num_circuits: int = 1,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    oat_c: float = 15.0,
    altimeter_inhg: float = 29.92,
    field_elev_ft: float = 0.0,
    ac: dict = None,
    weight_lb: float = None,
    power_setting: float = 0.5,
    cg_position: float = 0.5,
    entry_distance_nm: float = 0.3,
    turn_bank_deg: float = 30.0,
    points_per_leg: int = 20,
    points_per_turn: int = 24,  # More points for smoother turn rendering
) -> tuple:
    """
    Simulate rectangular course with PERFECT ground track geometry.

    The path follows exact ground track over the field boundaries.
    At each point, we calculate the required bank/heading/crab.
    """
    # Validate inputs
    if not dw_start or not dw_end:
        return [], [], {}
    if not dw_start.get('lat') or not dw_end.get('lat'):
        return [], [], {}

    # Parse parameters
    altitude_ft = float(altitude_ft or 800.0)
    ias_knots = float(ias_knots or 95.0)
    lateral_offset_nm = float(lateral_offset_nm or 0.75)
    wind_dir_deg = float(wind_dir_deg or 0.0)
    wind_speed_kt = float(wind_speed_kt or 0.0)
    oat_c = float(oat_c if oat_c is not None else 15.0)
    altimeter_inhg = float(altimeter_inhg if altimeter_inhg is not None else 29.92)
    field_elev_ft = float(field_elev_ft or 0.0)
    entry_distance_nm = float(entry_distance_nm or 0.3)
    turn_bank_deg = float(turn_bank_deg or 30.0)

    is_left = str(pattern_direction).lower().startswith('l')
    turn_dir = -1 if is_left else 1  # -1 = left turns, +1 = right turns

    # Aircraft data
    if ac is None:
        ac = {}
    if weight_lb is None or weight_lb <= 0:
        weight_lb = ac.get("total_weight_lb") or _ref_weight_lb(ac) or 2300.0
    weight_lb = float(weight_lb)

    # Compute TAS
    alt_msl = field_elev_ft + altitude_ft
    pressure_alt = compute_pressure_altitude(alt_msl, altimeter_inhg)
    tas_knots = compute_true_airspeed(ias_knots, pressure_alt, oat_c)
    tas_knots = float(tas_knots) if tas_knots and tas_knots > 1 else ias_knots
    tas_fps = tas_knots * 1.68781

    # Standard turn radius at specified bank
    bank_rad = math.radians(turn_bank_deg)
    std_turn_radius_ft = (tas_fps ** 2) / (G_FPS2 * math.tan(bank_rad))

    # Wind vector (direction wind is blowing TO, in NE frame)
    wind_to_deg = _wrap_360(wind_dir_deg + 180.0)
    wind_to_rad = math.radians(wind_to_deg)
    wind_fps = wind_speed_kt * 1.68781
    wn_fps = wind_fps * math.cos(wind_to_rad)
    we_fps = wind_fps * math.sin(wind_to_rad)

    # =========================================================================
    # GEOMETRY SETUP - Define the PERFECT rectangle
    # =========================================================================

    lat1, lon1 = dw_start['lat'], dw_start['lon']
    lat2, lon2 = dw_end['lat'], dw_end['lon']

    # Midpoint of downwind
    mid_lat = (lat1 + lat2) / 2
    mid_lon = (lon1 + lon2) / 2

    # Conversion factors
    ft_per_deg_lat = 364567.2
    ft_per_deg_lon = 364567.2 * math.cos(math.radians(mid_lat))

    def to_local(lat, lon):
        return (lat - mid_lat) * ft_per_deg_lat, (lon - mid_lon) * ft_per_deg_lon

    def to_latlon(n_ft, e_ft):
        return mid_lat + n_ft / ft_per_deg_lat, mid_lon + e_ft / ft_per_deg_lon

    # Downwind leg in local coords
    dw_start_n, dw_start_e = to_local(lat1, lon1)
    dw_end_n, dw_end_e = to_local(lat2, lon2)
    mid_n, mid_e = 0.0, 0.0

    # Downwind track (the direction of flight on downwind leg)
    dw_track_deg = _wrap_360(math.degrees(math.atan2(dw_end_e - dw_start_e, dw_end_n - dw_start_n)))
    dw_track_rad = math.radians(dw_track_deg)

    # Track directions for each leg
    base_track_deg = _wrap_360(dw_track_deg + turn_dir * 90)  # 90° turn from downwind
    upwind_track_deg = _wrap_360(dw_track_deg + 180)          # Opposite of downwind
    crosswind_track_deg = _wrap_360(dw_track_deg - turn_dir * 90)  # Back toward downwind

    # Unit vectors
    dw_unit_n = math.cos(dw_track_rad)
    dw_unit_e = math.sin(dw_track_rad)

    # Perpendicular unit vector (toward the pattern side)
    # For left pattern: pattern is to the LEFT of pilot (90° left of heading)
    # For right pattern: pattern is to the RIGHT of pilot (90° right of heading)
    # Flying north (0°), left is west (0, -1), right is east (0, 1)
    if is_left:
        perp_unit_n = dw_unit_e    # 90° left of heading
        perp_unit_e = -dw_unit_n
    else:
        perp_unit_n = -dw_unit_e   # 90° right of heading
        perp_unit_e = dw_unit_n

    # Dimensions
    dw_length_ft = math.hypot(dw_end_n - dw_start_n, dw_end_e - dw_start_e)
    lateral_offset_ft = lateral_offset_nm * FT_PER_NM
    entry_dist_ft = entry_distance_nm * FT_PER_NM
    turn_radius_ft = min(std_turn_radius_ft, lateral_offset_ft / 3, dw_length_ft / 4)

    # =========================================================================
    # DEFINE RECTANGLE CORNER POINTS (where straight legs meet)
    # The actual ground track will have rounded corners
    # =========================================================================

    # Corner A: end of downwind / start of base (dw_end)
    corner_a_n, corner_a_e = dw_end_n, dw_end_e

    # Corner B: end of base / start of upwind
    corner_b_n = corner_a_n + perp_unit_n * lateral_offset_ft
    corner_b_e = corner_a_e + perp_unit_e * lateral_offset_ft

    # Corner C: end of upwind / start of crosswind
    corner_c_n = corner_b_n - dw_unit_n * dw_length_ft
    corner_c_e = corner_b_e - dw_unit_e * dw_length_ft

    # Corner D: end of crosswind / start of downwind (dw_start)
    corner_d_n, corner_d_e = dw_start_n, dw_start_e

    # =========================================================================
    # 45° ENTRY
    # =========================================================================

    if is_left:
        entry_track_deg = _wrap_360(dw_track_deg - 45)  # From right (outside)
    else:
        entry_track_deg = _wrap_360(dw_track_deg + 45)  # From left (outside)

    entry_track_rad = math.radians(entry_track_deg)
    entry_unit_n = math.cos(entry_track_rad)
    entry_unit_e = math.sin(entry_track_rad)

    entry_start_n = mid_n - entry_unit_n * entry_dist_ft
    entry_start_e = mid_e - entry_unit_e * entry_dist_ft

    # =========================================================================
    # FLIGHT PARAMETER CALCULATIONS
    # =========================================================================

    def calc_flight_params(track_deg, bank_deg=0.0):
        """
        Given the desired ground TRACK, calculate the required HEADING and resulting groundspeed.
        This is the wind triangle solution.
        """
        track_rad = math.radians(track_deg)
        track_n = math.cos(track_rad)
        track_e = math.sin(track_rad)

        # Wind components along and across desired track
        wind_along = wn_fps * track_n + we_fps * track_e
        wind_across = we_fps * track_n - wn_fps * track_e

        # Crab angle needed to correct for crosswind
        # sin(crab) = -wind_across / TAS
        cross_ratio = wind_across / tas_fps
        cross_ratio = max(-0.95, min(0.95, cross_ratio))
        crab_rad = math.asin(-cross_ratio)
        crab_deg = math.degrees(crab_rad)

        # Required heading to maintain track
        hdg_deg = _wrap_360(track_deg + crab_deg)

        # Resulting groundspeed
        gs_fps = tas_fps * math.cos(crab_rad) + wind_along
        gs_fps = max(10.0, gs_fps)
        gs_kt = gs_fps / 1.68781

        return hdg_deg, gs_kt, crab_deg, gs_fps

    # =========================================================================
    # PATH GENERATION - Build the perfect ground track
    # =========================================================================

    path = []
    hover = []
    time_sec = 0.0
    stats = {"max_bank": 0.0, "min_bank": 90.0, "max_gs": 0.0, "min_gs": 999.0, "max_crab": 0.0}

    def add_point(n_ft, e_ft, track_deg, segment, bank_deg=0.0):
        """Add a point on the perfect ground track with calculated flight params."""
        nonlocal time_sec

        lat, lon = to_latlon(n_ft, e_ft)
        hdg_deg, gs_kt, crab_deg, gs_fps = calc_flight_params(track_deg, bank_deg)

        # Update stats
        if abs(bank_deg) > stats["max_bank"]:
            stats["max_bank"] = abs(bank_deg)
        if 0 < abs(bank_deg) < stats["min_bank"]:
            stats["min_bank"] = abs(bank_deg)
        if gs_kt > stats["max_gs"]:
            stats["max_gs"] = gs_kt
        if gs_kt < stats["min_gs"]:
            stats["min_gs"] = gs_kt
        if abs(crab_deg) > stats["max_crab"]:
            stats["max_crab"] = abs(crab_deg)

        path.append([lat, lon])
        hover.append({
            "time": round(time_sec, 1),
            "alt": round(altitude_ft, 0),
            "tas": round(tas_knots, 1),
            "ias": round(ias_knots, 1),
            "gs": round(gs_kt, 1),
            "aob": round(bank_deg, 1),
            "vs": 0,
            "track": round(track_deg, 1),
            "heading": round(hdg_deg, 1),
            "crab": _format_crab(crab_deg),
            "segment": segment,
        })

        return gs_fps

    def generate_straight_leg(start_n, start_e, end_n, end_e, track_deg, segment, n_points):
        """Generate points along a straight leg (perfect ground track)."""
        nonlocal time_sec

        dn = end_n - start_n
        de = end_e - start_e
        length = math.hypot(dn, de)

        if length < 1:
            return

        for i in range(n_points):
            t = i / max(1, n_points - 1)
            n = start_n + t * dn
            e = start_e + t * de

            gs_fps = add_point(n, e, track_deg, segment, 0.0)

            if i > 0:
                seg_dist = length / (n_points - 1)
                time_sec += seg_dist / gs_fps

    def generate_turn(center_n, center_e, radius, start_track_deg, end_track_deg, direction, segment, n_points):
        """
        Generate points along a turn arc (perfect circular ground track).
        The turn smoothly transitions from start_track to end_track.
        """
        nonlocal time_sec

        # Calculate start and end angles (position angles from center)
        # Position angle is 90° offset from track direction
        start_pos_angle = _wrap_360(start_track_deg - direction * 90)
        end_pos_angle = _wrap_360(end_track_deg - direction * 90)

        # Calculate sweep angle
        sweep = end_pos_angle - start_pos_angle
        if direction == -1:  # Left turn
            if sweep > 0:
                sweep -= 360
        else:  # Right turn
            if sweep < 0:
                sweep += 360

        for i in range(n_points):
            t = i / max(1, n_points - 1)

            # Current position angle
            pos_angle_deg = start_pos_angle + t * sweep
            pos_angle_rad = math.radians(pos_angle_deg)

            # Position on the arc
            n = center_n + radius * math.cos(pos_angle_rad)
            e = center_e + radius * math.sin(pos_angle_rad)

            # Track is tangent to circle (perpendicular to radius)
            track_deg = _wrap_360(pos_angle_deg + direction * 90)

            # Calculate required bank for this turn radius at current groundspeed
            _, gs_kt, _, gs_fps = calc_flight_params(track_deg)

            # Bank angle: tan(bank) = V² / (g * R)
            if radius > 10:
                centripetal = (gs_fps ** 2) / radius
                bank_rad = math.atan(centripetal / G_FPS2)
                bank_deg = math.degrees(bank_rad) * direction
                bank_deg = max(-45, min(45, bank_deg))
            else:
                bank_deg = 0.0

            add_point(n, e, track_deg, segment, bank_deg)

            if i > 0:
                arc_len = radius * abs(sweep) / (n_points - 1) * math.pi / 180
                time_sec += arc_len / gs_fps

    # =========================================================================
    # BUILD THE PATH
    # =========================================================================

    # 1. Entry leg (45° approach to midpoint)
    generate_straight_leg(entry_start_n, entry_start_e, mid_n, mid_e,
                          entry_track_deg, "entry", points_per_leg)

    # 2. Entry turn (45° turn to align with downwind)
    # Entry turn is OPPOSITE direction of pattern turns:
    # - Left pattern: entry turn is RIGHT (from 315° to 0°)
    # - Right pattern: entry turn is LEFT (from 45° to 0°)
    #
    # KEY: Turn center is positioned so turn ENDS on the downwind leg at midpoint
    # (not so turn STARTS at midpoint - that would overshoot)
    entry_turn_dir = -turn_dir  # Opposite of pattern turn direction

    # Turn center is perpendicular to DOWNWIND track (where we want to end up)
    # For right turn ending on track 0°: center is 90° right = east
    # For left turn ending on track 0°: center is 90° left = west
    dw_perp_deg = _wrap_360(dw_track_deg + entry_turn_dir * 90)
    dw_perp_rad = math.radians(dw_perp_deg)
    entry_turn_center_n = mid_n + turn_radius_ft * math.cos(dw_perp_rad)
    entry_turn_center_e = mid_e + turn_radius_ft * math.sin(dw_perp_rad)

    # Calculate where the turn STARTS (this is where entry leg should end)
    entry_turn_start_angle = _wrap_360(entry_track_deg - entry_turn_dir * 90)
    entry_turn_start_n = entry_turn_center_n + turn_radius_ft * math.cos(math.radians(entry_turn_start_angle))
    entry_turn_start_e = entry_turn_center_e + turn_radius_ft * math.sin(math.radians(entry_turn_start_angle))

    # Re-generate entry leg to end at the turn start point (not midpoint)
    # Clear the entry leg we generated earlier and regenerate
    entry_leg_count = points_per_leg
    path = path[:-entry_leg_count]
    hover = hover[:-entry_leg_count]
    time_sec = 0.0
    generate_straight_leg(entry_start_n, entry_start_e, entry_turn_start_n, entry_turn_start_e,
                          entry_track_deg, "entry", points_per_leg)

    # Now generate the turn
    generate_turn(entry_turn_center_n, entry_turn_center_e, turn_radius_ft,
                  entry_track_deg, dw_track_deg, entry_turn_dir, "entry_turn", points_per_turn)

    # Turn ends at midpoint, on downwind heading
    cur_n, cur_e = mid_n, mid_e

    # Circuit(s)
    for _ in range(num_circuits):
        # 3. Downwind leg to corner A (minus turn radius for smooth corner)
        dw_leg_end_n = corner_a_n - dw_unit_n * turn_radius_ft
        dw_leg_end_e = corner_a_e - dw_unit_e * turn_radius_ft
        generate_straight_leg(cur_n, cur_e, dw_leg_end_n, dw_leg_end_e,
                              dw_track_deg, "downwind", points_per_leg)
        cur_n, cur_e = dw_leg_end_n, dw_leg_end_e

        # 4. Turn A (downwind to base)
        turn_a_center_n = cur_n + perp_unit_n * turn_radius_ft
        turn_a_center_e = cur_e + perp_unit_e * turn_radius_ft
        generate_turn(turn_a_center_n, turn_a_center_e, turn_radius_ft,
                      dw_track_deg, base_track_deg, turn_dir, "turn_to_base", points_per_turn)
        # Update position after turn
        turn_a_end_angle = _wrap_360(base_track_deg - turn_dir * 90)
        cur_n = turn_a_center_n + turn_radius_ft * math.cos(math.radians(turn_a_end_angle))
        cur_e = turn_a_center_e + turn_radius_ft * math.sin(math.radians(turn_a_end_angle))

        # 5. Base leg to corner B (minus turn radius)
        base_leg_end_n = corner_b_n - perp_unit_n * turn_radius_ft
        base_leg_end_e = corner_b_e - perp_unit_e * turn_radius_ft
        generate_straight_leg(cur_n, cur_e, base_leg_end_n, base_leg_end_e,
                              base_track_deg, "base", points_per_leg)
        cur_n, cur_e = base_leg_end_n, base_leg_end_e

        # 6. Turn B (base to upwind)
        upwind_unit_n = -dw_unit_n
        upwind_unit_e = -dw_unit_e
        turn_b_center_n = cur_n + upwind_unit_n * turn_radius_ft
        turn_b_center_e = cur_e + upwind_unit_e * turn_radius_ft
        generate_turn(turn_b_center_n, turn_b_center_e, turn_radius_ft,
                      base_track_deg, upwind_track_deg, turn_dir, "turn_to_upwind", points_per_turn)
        turn_b_end_angle = _wrap_360(upwind_track_deg - turn_dir * 90)
        cur_n = turn_b_center_n + turn_radius_ft * math.cos(math.radians(turn_b_end_angle))
        cur_e = turn_b_center_e + turn_radius_ft * math.sin(math.radians(turn_b_end_angle))

        # 7. Upwind leg to corner C (minus turn radius)
        upwind_leg_end_n = corner_c_n + dw_unit_n * turn_radius_ft
        upwind_leg_end_e = corner_c_e + dw_unit_e * turn_radius_ft
        generate_straight_leg(cur_n, cur_e, upwind_leg_end_n, upwind_leg_end_e,
                              upwind_track_deg, "upwind", points_per_leg)
        cur_n, cur_e = upwind_leg_end_n, upwind_leg_end_e

        # 8. Turn C (upwind to crosswind)
        turn_c_center_n = cur_n - perp_unit_n * turn_radius_ft
        turn_c_center_e = cur_e - perp_unit_e * turn_radius_ft
        generate_turn(turn_c_center_n, turn_c_center_e, turn_radius_ft,
                      upwind_track_deg, crosswind_track_deg, turn_dir, "turn_to_crosswind", points_per_turn)
        turn_c_end_angle = _wrap_360(crosswind_track_deg - turn_dir * 90)
        cur_n = turn_c_center_n + turn_radius_ft * math.cos(math.radians(turn_c_end_angle))
        cur_e = turn_c_center_e + turn_radius_ft * math.sin(math.radians(turn_c_end_angle))

        # 9. Crosswind leg to corner D (minus turn radius)
        xwind_leg_end_n = corner_d_n + perp_unit_n * turn_radius_ft
        xwind_leg_end_e = corner_d_e + perp_unit_e * turn_radius_ft
        generate_straight_leg(cur_n, cur_e, xwind_leg_end_n, xwind_leg_end_e,
                              crosswind_track_deg, "crosswind", points_per_leg)
        cur_n, cur_e = xwind_leg_end_n, xwind_leg_end_e

        # 10. Turn D (crosswind to downwind)
        turn_d_center_n = cur_n + dw_unit_n * turn_radius_ft
        turn_d_center_e = cur_e + dw_unit_e * turn_radius_ft
        generate_turn(turn_d_center_n, turn_d_center_e, turn_radius_ft,
                      crosswind_track_deg, dw_track_deg, turn_dir, "turn_to_downwind", points_per_turn)
        turn_d_end_angle = _wrap_360(dw_track_deg - turn_dir * 90)
        cur_n = turn_d_center_n + turn_radius_ft * math.cos(math.radians(turn_d_end_angle))
        cur_e = turn_d_center_e + turn_radius_ft * math.sin(math.radians(turn_d_end_angle))

        # 11. Downwind back to midpoint
        generate_straight_leg(cur_n, cur_e, mid_n, mid_e,
                              dw_track_deg, "downwind", points_per_leg)
        cur_n, cur_e = mid_n, mid_e

    # =========================================================================
    # WARNINGS AND METADATA
    # =========================================================================

    warnings = {
        "stall_margin_warning": False,
        "g_limit_warning": False,
        "airspeed_warning": None,
        "bank_limited": False,
        "power_setting_pct": round(power_setting * 100 if power_setting else 50),
        "cg_position_pct": round(cg_position * 100 if cg_position else 50),
        "dw_length_nm": round(dw_length_ft / FT_PER_NM, 3),
        "lateral_offset_nm": round(lateral_offset_nm, 3),
        "dw_track": round(dw_track_deg, 0),
        "pattern_direction": pattern_direction,
        "turn_radius_ft": round(turn_radius_ft, 0),
        "max_bank_achieved": round(stats["max_bank"], 1),
        "min_bank_achieved": round(stats["min_bank"], 1) if stats["min_bank"] < 90 else 0.0,
        "max_groundspeed": round(stats["max_gs"], 1),
        "min_groundspeed": round(stats["min_gs"], 1),
        "max_crab_angle": round(stats["max_crab"], 1),
        "total_time_sec": round(time_sec, 1),
        "weight_lb": round(weight_lb, 0),
        "tas_knots": round(tas_knots, 1),
        "stall_speed_clean": 48.0,
        "density_altitude_ft": round(pressure_alt, 0),
        "entry_altitude_ft": round(altitude_ft, 0),
        "final_altitude_ft": round(altitude_ft, 0),
        "altitude_loss_ft": 0,
        "wind_dir": round(wind_dir_deg, 0),
        "wind_speed": round(wind_speed_kt, 0),
    }

    return path, hover, warnings
