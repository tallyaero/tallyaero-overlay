"""
Eights on Pylons simulation module.

Eights on Pylons is a commercial pilot maneuver where the aircraft flies a
figure-8 pattern around two reference points (pylons). The wing tip reference
appears to pivot on each pylon when flown at the correct PIVOTAL ALTITUDE.

GEOMETRY:
- 180° turn around Pylon 1
- Transition (tangent line) crossing to Pylon 2
- 180° turn around Pylon 2 in OPPOSITE direction
- Transition (tangent line) crossing back to Pylon 1
- Repeat

PIVOTAL ALTITUDE: PA = GS² / 11.3 (GS in knots, PA in feet AGL)

The altitude varies continuously with groundspeed:
- Higher altitude when flying downwind (faster GS)
- Lower altitude when flying upwind (slower GS)

Reference: FAA Airplane Flying Handbook (FAA-H-8083-3C), Chapter 7
Commercial Pilot ACS: Area of Operation V, Task E

Key standards:
- Bank angle: Maximum 30-40° per ACS
- Pylons: 0.5-1.0 NM apart, perpendicular to wind
- Entry: Below Va (maneuvering speed)
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


def _angle_diff_deg(a: float, b: float) -> float:
    """Compute signed difference (a - b), result in [-180, 180]."""
    diff = (a - b + 540.0) % 360.0 - 180.0
    return diff


def _get_stall_speed_for_weight(ac: dict, weight_lb: float, flap_config: str = "clean") -> float:
    """Get the stall speed adjusted for current weight."""
    stall_data = ac.get("stall_speeds")
    if stall_data:
        config_data = stall_data.get(flap_config, stall_data.get("clean", {}))
        weights = config_data.get("weights", [])
        speeds = config_data.get("speeds", [])
        if weights and speeds and len(weights) == len(speeds):
            if weight_lb <= weights[0]:
                return float(speeds[0])
            if weight_lb >= weights[-1]:
                return float(speeds[-1])
            for i in range(len(weights) - 1):
                if weights[i] <= weight_lb <= weights[i + 1]:
                    w_ratio = (weight_lb - weights[i]) / (weights[i + 1] - weights[i])
                    return speeds[i] + w_ratio * (speeds[i + 1] - speeds[i])

    sel = ac.get("single_engine_limits", {})
    vs_ref = sel.get("vs", sel.get("vs0", 48.0))
    w_ref = _ref_weight_lb(ac)
    if w_ref and w_ref > 0 and weight_lb > 0:
        return float(vs_ref) * math.sqrt(weight_lb / w_ref)
    return float(vs_ref)


def _get_maneuvering_speed(ac: dict, weight_lb: float) -> float:
    """Get maneuvering speed (Va) adjusted for weight."""
    va_ref = ac.get("Va", ac.get("maneuvering_speed", 105.0))
    w_max = ac.get("max_weight", ac.get("max_takeoff_weight", 2550.0))
    if w_max > 0 and weight_lb > 0:
        return float(va_ref) * math.sqrt(weight_lb / w_max)
    return float(va_ref)


def compute_pivotal_altitude(groundspeed_kt: float) -> float:
    """
    Compute the pivotal altitude for a given groundspeed.

    Formula: PA = GS² / 11.3 (with GS in knots, PA in feet AGL)
    """
    return (groundspeed_kt ** 2) / 11.3


def simulate_eights_on_pylons(
    pylon1: dict,
    pylon2: dict,
    ias_knots: float = 100.0,
    num_eights: int = 1,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    oat_c: float = 15.0,
    altimeter_inhg: float = 29.92,
    field_elev_ft: float = 0.0,
    ac: dict = None,
    weight_lb: float = None,
    power_setting: float = 0.65,
    cg_position: float = 0.5,
    bank_angle_deg: float = 30.0,
    angular_step_deg: float = 3.0,
    entry_direction: str = "downwind",
) -> tuple:
    """
    Simulate Eights on Pylons with integrated pivotal altitude calculator.

    The figure-8 consists of:
    - 180° arc around Pylon 1
    - Transition to Pylon 2
    - 180° arc around Pylon 2 (opposite direction)
    - Transition back to Pylon 1

    Args:
        pylon1: Dict with 'lat' and 'lon' - first pylon position
        pylon2: Dict with 'lat' and 'lon' - second pylon position
        ias_knots: Indicated airspeed in knots (must be below Va)
        num_eights: Number of complete figure-8s (1-3)
        wind_dir_deg: Wind direction (FROM) in degrees
        wind_speed_kt: Wind speed in knots
        bank_angle_deg: Target bank angle for turns (25-40°)

    Returns:
        Tuple of (path, hover_data, warnings)
    """
    if pylon1 is None or pylon2 is None:
        return [], [], {}
    if not pylon1.get('lat') or not pylon2.get('lat'):
        return [], [], {}

    # Parse inputs
    ias_knots = float(ias_knots or 100.0)
    wind_dir_deg = float(wind_dir_deg or 0.0)
    wind_speed_kt = float(wind_speed_kt or 0.0)
    oat_c = float(oat_c if oat_c is not None else 15.0)
    altimeter_inhg = float(altimeter_inhg if altimeter_inhg is not None else 29.92)
    field_elev_ft = float(field_elev_ft or 0.0)
    num_eights = max(1, min(3, int(num_eights or 1)))
    bank_angle_deg = max(20.0, min(40.0, float(bank_angle_deg or 30.0)))
    angular_step_deg = max(1.0, min(10.0, float(angular_step_deg or 3.0)))

    power_setting = max(0.05, min(1.0, float(power_setting or 0.65)))
    cg_position = max(0.0, min(1.0, float(cg_position or 0.5)))

    # Aircraft data
    if ac is None:
        ac = {}
    if weight_lb is None or weight_lb <= 0:
        weight_lb = ac.get("total_weight_lb") or _ref_weight_lb(ac) or 2300.0
    weight_lb = float(weight_lb)

    # Performance limits
    stall_speed_base = _get_stall_speed_for_weight(ac, weight_lb, "clean")
    cg_stall_factor = 1.0 + (0.5 - cg_position) * 0.04
    stall_speed_clean = stall_speed_base * cg_stall_factor
    maneuvering_speed = _get_maneuvering_speed(ac, weight_lb)

    warnings = {
        "stall_margin_warning": False,
        "g_limit_warning": False,
        "airspeed_warning": None,
        "bank_limited": False,
        "power_setting_pct": round(power_setting * 100, 0),
        "cg_position_pct": round(cg_position * 100, 0),
    }

    # Airspeed checks
    min_safe_ias = stall_speed_clean * 1.3
    if ias_knots < min_safe_ias:
        warnings["airspeed_warning"] = f"IAS {ias_knots:.0f} kt below 1.3×Vs ({min_safe_ias:.0f} kt)"
        ias_knots = min_safe_ias
    if ias_knots > maneuvering_speed:
        warnings["airspeed_warning"] = f"IAS {ias_knots:.0f} kt exceeds Va ({maneuvering_speed:.0f} kt)"

    # Compute TAS
    estimated_pa = compute_pivotal_altitude(ias_knots)
    alt_msl_ft = field_elev_ft + estimated_pa
    pressure_alt_ft = compute_pressure_altitude(alt_msl_ft, altimeter_inhg)
    tas_knots = compute_true_airspeed(ias_knots, pressure_alt_ft, oat_c)
    tas_knots = float(tas_knots) if tas_knots and tas_knots > 1 else ias_knots
    tas_fps = tas_knots * 1.68781

    # Wind vector (TO direction)
    wind_to_deg = _wrap_360(wind_dir_deg + 180.0)
    wind_to_rad = math.radians(wind_to_deg)
    wind_fps = wind_speed_kt * 1.68781
    wn_fps = wind_fps * math.cos(wind_to_rad)
    we_fps = wind_fps * math.sin(wind_to_rad)

    # Turn radius from bank angle and TAS
    bank_rad = math.radians(bank_angle_deg)
    turn_radius_ft = (tas_fps ** 2) / (G_FPS2 * math.tan(bank_rad))

    # =========================================================================
    # GEOMETRY SETUP
    # =========================================================================

    p1_lat, p1_lon = pylon1['lat'], pylon1['lon']
    p2_lat, p2_lon = pylon2['lat'], pylon2['lon']
    mid_lat = (p1_lat + p2_lat) / 2
    mid_lon = (p1_lon + p2_lon) / 2

    ft_per_deg_lat = 364567.2
    ft_per_deg_lon = 364567.2 * math.cos(math.radians(mid_lat))

    def to_local(lat, lon):
        return (lat - mid_lat) * ft_per_deg_lat, (lon - mid_lon) * ft_per_deg_lon

    def to_latlon(n_ft, e_ft):
        return mid_lat + n_ft / ft_per_deg_lat, mid_lon + e_ft / ft_per_deg_lon

    p1_n, p1_e = to_local(p1_lat, p1_lon)
    p2_n, p2_e = to_local(p2_lat, p2_lon)

    # Pylon axis (line between pylons)
    pylon_dist_ft = math.hypot(p2_n - p1_n, p2_e - p1_e)
    pylon_dist_nm = pylon_dist_ft / FT_PER_NM
    pylon_axis_deg = _wrap_360(math.degrees(math.atan2(p2_e - p1_e, p2_n - p1_n)))
    pylon_axis_rad = math.radians(pylon_axis_deg)

    # Unit vectors along and perpendicular to pylon axis
    axis_unit_n = math.cos(pylon_axis_rad)
    axis_unit_e = math.sin(pylon_axis_rad)
    # Perpendicular (to the left of axis direction)
    perp_unit_n = -axis_unit_e
    perp_unit_e = axis_unit_n

    # Determine which side of the axis to put each semicircle
    # Wind direction affects which pylon is "downwind"
    # Standard: semicircles are on OPPOSITE sides of the axis

    # Check wind relative to pylon axis
    wind_cross = math.sin(math.radians(wind_to_deg - pylon_axis_deg))

    # If wind has component perpendicular to axis, one side is "downwind"
    # Pylon 1 semicircle on one side, Pylon 2 on the other
    if wind_cross >= 0:
        # Wind pushes toward positive perp side
        p1_side = 1   # Pylon 1 semicircle on positive perp side
        p2_side = -1  # Pylon 2 semicircle on negative perp side
    else:
        p1_side = -1
        p2_side = 1

    # Limit turn radius to fit geometry (can't be larger than half pylon distance)
    max_radius = pylon_dist_ft * 0.4
    if turn_radius_ft > max_radius:
        turn_radius_ft = max_radius
        warnings["bank_limited"] = True

    # =========================================================================
    # HELPER FUNCTIONS
    # =========================================================================

    path = []
    hover = []
    total_time = 0.0
    max_bank = 0.0
    min_bank = 90.0
    max_gs = 0.0
    min_gs = 999.0
    max_pa = 0.0
    min_pa = 9999.0

    def calc_flight_params(track_deg):
        """Calculate groundspeed, heading, crab for a given track."""
        track_rad = math.radians(track_deg)
        track_n = math.cos(track_rad)
        track_e = math.sin(track_rad)

        wind_along = wn_fps * track_n + we_fps * track_e
        wind_across = -wn_fps * track_e + we_fps * track_n

        cross_ratio = wind_across / max(tas_fps, 50.0)
        cross_ratio = max(-0.95, min(0.95, cross_ratio))
        crab_rad = math.asin(-cross_ratio)
        crab_deg = math.degrees(crab_rad)

        hdg_deg = _wrap_360(track_deg + crab_deg)
        gs_fps = tas_fps * math.cos(crab_rad) + wind_along
        gs_fps = max(30.0, gs_fps)
        gs_kt = gs_fps / 1.68781

        return gs_kt, hdg_deg, crab_deg, gs_fps

    def add_point(n_ft, e_ft, track_deg, bank_deg, segment):
        """Add a point to the path with flight parameters."""
        nonlocal total_time, max_bank, min_bank, max_gs, min_gs, max_pa, min_pa

        gs_kt, hdg_deg, crab_deg, gs_fps = calc_flight_params(track_deg)
        pivotal_alt = compute_pivotal_altitude(gs_kt)

        # Update statistics
        if abs(bank_deg) > max_bank:
            max_bank = abs(bank_deg)
        if abs(bank_deg) > 0 and abs(bank_deg) < min_bank:
            min_bank = abs(bank_deg)
        if gs_kt > max_gs:
            max_gs = gs_kt
        if gs_kt < min_gs:
            min_gs = gs_kt
        if pivotal_alt > max_pa:
            max_pa = pivotal_alt
        if pivotal_alt < min_pa:
            min_pa = pivotal_alt

        # Load factor
        if abs(bank_deg) > 1:
            load_factor = 1.0 / math.cos(math.radians(abs(bank_deg)))
        else:
            load_factor = 1.0

        # Stall check
        stall_in_turn = stall_speed_clean * math.sqrt(load_factor)
        if ias_knots / stall_in_turn < 1.2:
            warnings["stall_margin_warning"] = True

        lat, lon = to_latlon(n_ft, e_ft)
        path.append([lat, lon])
        hover.append({
            "time": round(total_time, 2),
            "alt": round(pivotal_alt, 0),
            "pivotal_alt": round(pivotal_alt, 0),
            "tas": round(tas_knots, 1),
            "ias": round(ias_knots, 1),
            "gs": round(gs_kt, 1),
            "aob": round(bank_deg, 1),
            "vs": 0,
            "track": round(track_deg, 1),
            "heading": round(hdg_deg, 1),
            "wind_correction": round(crab_deg, 1),
            "load_factor": round(load_factor, 2),
            "segment": segment,
        })

        return gs_fps

    def generate_arc_from_position(entry_n, entry_e, entry_track_deg,
                                    center_n, center_e, turn_dir,
                                    target_pylon_n, target_pylon_e, segment,
                                    min_arc_deg=120.0, max_arc_deg=240.0):
        """
        Generate an arc starting from a specific position and track.

        The arc continues until the track aligns with the direction to the
        NEXT PYLON CENTER, creating smooth tangent transitions.

        Args:
            entry_n, entry_e: Actual entry position (from transition)
            entry_track_deg: Entry track (from transition)
            center_n, center_e: Pylon center position
            turn_dir: +1 for right, -1 for left
            target_pylon_n, target_pylon_e: CENTER of the next pylon
            segment: Segment name for hover data
            min_arc_deg: Minimum arc (ensures proper loop shape)
            max_arc_deg: Maximum arc (safety limit)

        Returns:
            (exit_n, exit_e, exit_track, arc_degrees)
        """
        nonlocal total_time

        # Calculate actual radius and starting position angle from entry point
        vec_n = entry_n - center_n
        vec_e = entry_e - center_e
        actual_radius = math.hypot(vec_n, vec_e)
        start_pos_angle = _wrap_360(math.degrees(math.atan2(vec_e, vec_n)))

        # Use the actual radius for this arc (may differ slightly from target)
        radius = actual_radius if actual_radius > 100 else turn_radius_ft

        # Step through the arc
        arc_flown = 0.0
        step = 0
        exit_n, exit_e, exit_track = entry_n, entry_e, entry_track_deg
        pos_angle_deg = start_pos_angle

        while arc_flown <= max_arc_deg:
            progress = step * angular_step_deg

            # Current position angle on the circle
            if turn_dir > 0:
                pos_angle_deg = _wrap_360(start_pos_angle + progress)
            else:
                pos_angle_deg = _wrap_360(start_pos_angle - progress)

            pos_angle_rad = math.radians(pos_angle_deg)

            # Position on circle
            n = center_n + radius * math.cos(pos_angle_rad)
            e = center_e + radius * math.sin(pos_angle_rad)

            # Track is tangent to circle
            # For first point, use passed-in track to ensure continuity
            if step == 0:
                track_deg = entry_track_deg
                n, e = entry_n, entry_e  # Use exact entry position
            else:
                track_deg = _wrap_360(pos_angle_deg + turn_dir * 90)

            # Bank angle
            bank = bank_angle_deg * turn_dir

            gs_fps = add_point(n, e, track_deg, bank, segment)

            if step > 0:
                arc_len = radius * math.radians(angular_step_deg)
                total_time += arc_len / gs_fps

            arc_flown = progress
            exit_n, exit_e, exit_track = n, e, track_deg

            # Check if we've turned enough AND are aligned with target PYLON
            if arc_flown >= min_arc_deg:
                # Calculate bearing to target pylon CENTER
                bearing_to_pylon = _wrap_360(math.degrees(
                    math.atan2(target_pylon_e - n, target_pylon_n - n)
                ))

                # Check if track is close enough to bearing toward pylon
                track_error = abs(_angle_diff_deg(track_deg, bearing_to_pylon))
                if track_error < angular_step_deg * 2.0:
                    # We're aligned with the pylon - exit the turn
                    break

            step += 1

        return exit_n, exit_e, exit_track, arc_flown

    def generate_transition_to_tangent(start_n, start_e, start_track_deg,
                                        pylon_n, pylon_e, radius, turn_dir, segment):
        """
        Generate a transition that flies toward a pylon and stops at tangent entry.

        The transition smoothly blends from the current track to the entry track
        for the next turn, ensuring continuous track throughout.

        Returns: (entry_n, entry_e, entry_track, transition_time_sec, transition_dist_ft)
        """
        nonlocal total_time

        # Calculate where we'll enter the next turn tangentially
        track_rad = math.radians(start_track_deg)
        track_n = math.cos(track_rad)
        track_e = math.sin(track_rad)

        # Vector from start to pylon
        to_pylon_n = pylon_n - start_n
        to_pylon_e = pylon_e - start_e

        # Project onto track direction to find closest approach
        along_track = to_pylon_n * track_n + to_pylon_e * track_e

        # Perpendicular distance from track line to pylon
        perp_n = to_pylon_n - along_track * track_n
        perp_e = to_pylon_e - along_track * track_e
        perp_dist = math.hypot(perp_n, perp_e)

        # Calculate tangent entry point
        if perp_dist > radius:
            dist_to_travel = math.hypot(to_pylon_n, to_pylon_e) - radius
        else:
            tangent_offset = math.sqrt(max(0, radius**2 - perp_dist**2))
            dist_to_travel = along_track - tangent_offset

        dist_to_travel = max(100, dist_to_travel)

        # Final position
        end_n = start_n + dist_to_travel * track_n
        end_e = start_e + dist_to_travel * track_e

        # Entry track for the turn - tangent to the circle at entry point
        entry_vec_n = end_n - pylon_n
        entry_vec_e = end_e - pylon_e
        pos_angle = _wrap_360(math.degrees(math.atan2(entry_vec_e, entry_vec_n)))
        entry_track = _wrap_360(pos_angle + turn_dir * 90)

        # Generate transition points with BLENDED track
        # Smoothly transition from start_track_deg to entry_track
        num_steps = max(5, int(dist_to_travel / 200))
        transition_time = 0.0

        # Calculate shortest angle difference for smooth blending
        track_diff = _angle_diff_deg(entry_track, start_track_deg)

        for step in range(num_steps + 1):
            t = step / num_steps
            n = start_n + t * dist_to_travel * track_n
            e = start_e + t * dist_to_travel * track_e

            # Blend track from start to end (smooth transition)
            # Use cubic easing for smoother transition
            ease_t = t * t * (3 - 2 * t)  # Smooth step function
            blended_track = _wrap_360(start_track_deg + track_diff * ease_t)

            gs_fps = add_point(n, e, blended_track, 0.0, segment)

            if step > 0:
                seg_dist = dist_to_travel / num_steps
                seg_time = seg_dist / gs_fps
                total_time += seg_time
                transition_time += seg_time

        return end_n, end_e, entry_track, transition_time, dist_to_travel

    def generate_transition(start_n, start_e, start_track, end_n, end_e, end_track, segment):
        """
        Generate a transition with smooth track blending.
        Blends from start_track to end_track over the transition distance.

        Returns: (end_track, transition_time_sec, transition_dist_ft)
        """
        nonlocal total_time

        dist = math.hypot(end_n - start_n, end_e - start_e)

        # Calculate track difference for smooth blending
        track_diff = _angle_diff_deg(end_track, start_track)

        num_steps = max(5, int(dist / 200))  # Point every ~200 ft
        transition_time = 0.0

        for step in range(num_steps + 1):
            t = step / num_steps
            n = start_n + t * (end_n - start_n)
            e = start_e + t * (end_e - start_e)

            # Smooth track blend using cubic easing
            ease_t = t * t * (3 - 2 * t)
            blended_track = _wrap_360(start_track + track_diff * ease_t)

            gs_fps = add_point(n, e, blended_track, 0.0, segment)

            if step > 0:
                seg_dist = dist / num_steps
                seg_time = seg_dist / gs_fps
                total_time += seg_time
                transition_time += seg_time

        return end_track, transition_time, dist

    # =========================================================================
    # BUILD THE FIGURE-8 (Symmetric 180° Arc Geometry)
    # =========================================================================
    #
    # For a clean figure-8:
    # - Each pylon arc is approximately 180°
    # - P1 and P2 turn in OPPOSITE directions
    # - Entry/exit points are positioned so transitions are smooth diagonals
    # - The figure-8 crosses in the middle (X-pattern)

    # Vector from P1 to P2
    p1_to_p2_n = p2_n - p1_n
    p1_to_p2_e = p2_e - p1_e
    p1_to_p2_deg = _wrap_360(math.degrees(math.atan2(p1_to_p2_e, p1_to_p2_n)))
    p2_to_p1_deg = _wrap_360(p1_to_p2_deg + 180)

    # Perpendicular directions to pylon axis
    perp_right_deg = _wrap_360(p1_to_p2_deg + 90)  # Right of axis
    perp_left_deg = _wrap_360(p1_to_p2_deg - 90)   # Left of axis

    # Determine turn directions based on wind
    # First turn should be INTO the wind when possible
    downwind_deg = _wrap_360(wind_dir_deg + 180)

    # Cross product to determine which side of axis is downwind
    axis_rad = math.radians(p1_to_p2_deg)
    axis_n = math.cos(axis_rad)
    axis_e = math.sin(axis_rad)
    wind_rad = math.radians(downwind_deg)
    wind_n = math.cos(wind_rad)
    wind_e = math.sin(wind_rad)
    cross = axis_n * wind_e - axis_e * wind_n

    # P1 turns one way, P2 turns opposite
    # Choose based on wind direction relative to pylon axis
    if cross >= 0:
        # Wind pushes toward "right" side of axis
        p1_turn_dir = +1  # RIGHT turn at P1
        p2_turn_dir = -1  # LEFT turn at P2
    else:
        # Wind pushes toward "left" side of axis
        p1_turn_dir = -1  # LEFT turn at P1
        p2_turn_dir = +1  # RIGHT turn at P2

    # Arc extent: ~210° creates good figure-8 shape with substantial loops
    arc_extent_deg = 210.0

    # =========================================================================
    # BUTTERFLY FIGURE-8 GEOMETRY
    # =========================================================================
    # For butterfly pattern:
    # - Exit tracks should roughly point toward the other pylon (for smooth transitions)
    # - Both arcs bulge toward the same general direction (downwind side)
    #
    # We achieve this by setting exit tracks to point toward the other pylon
    # with a slight offset, then computing entry from the arc extent.

    # Diagonal offset creates the butterfly crossing pattern
    diagonal_offset_deg = 20.0

    # P1 exit track should point roughly toward P2
    p1_exit_track = _wrap_360(p1_to_p2_deg + p1_turn_dir * diagonal_offset_deg)
    # P2 exit track should point roughly toward P1
    p2_exit_track = _wrap_360(p2_to_p1_deg + p2_turn_dir * diagonal_offset_deg)

    # Calculate exit PA from exit track
    # Track = PA + turn_dir * 90, so PA = track - turn_dir * 90
    p1_exit_pa = _wrap_360(p1_exit_track - p1_turn_dir * 90)
    p2_exit_pa = _wrap_360(p2_exit_track - p2_turn_dir * 90)

    # Entry PA is arc_extent_deg before exit (going backwards along the arc)
    p1_entry_pa = _wrap_360(p1_exit_pa - p1_turn_dir * arc_extent_deg)
    p2_entry_pa = _wrap_360(p2_exit_pa - p2_turn_dir * arc_extent_deg)

    # Calculate entry/exit positions and tracks
    p1_entry_n = p1_n + turn_radius_ft * math.cos(math.radians(p1_entry_pa))
    p1_entry_e = p1_e + turn_radius_ft * math.sin(math.radians(p1_entry_pa))
    p1_entry_track = _wrap_360(p1_entry_pa + p1_turn_dir * 90)

    p1_exit_n = p1_n + turn_radius_ft * math.cos(math.radians(p1_exit_pa))
    p1_exit_e = p1_e + turn_radius_ft * math.sin(math.radians(p1_exit_pa))
    p1_exit_track = _wrap_360(p1_exit_pa + p1_turn_dir * 90)

    p2_entry_n = p2_n + turn_radius_ft * math.cos(math.radians(p2_entry_pa))
    p2_entry_e = p2_e + turn_radius_ft * math.sin(math.radians(p2_entry_pa))
    p2_entry_track = _wrap_360(p2_entry_pa + p2_turn_dir * 90)

    p2_exit_n = p2_n + turn_radius_ft * math.cos(math.radians(p2_exit_pa))
    p2_exit_e = p2_e + turn_radius_ft * math.sin(math.radians(p2_exit_pa))
    p2_exit_track = _wrap_360(p2_exit_pa + p2_turn_dir * 90)

    # Store arc angles for reporting
    p1_arc_deg = arc_extent_deg
    p2_arc_deg = arc_extent_deg

    # Track transition times for ACS compliance (3-5 seconds recommended)
    transition_times = []
    transition_distances = []
    arc_degrees_flown = []

    def generate_arc(center_n, center_e, entry_pa, arc_degrees, turn_dir, segment):
        """
        Generate an arc starting at entry_pa, turning arc_degrees in turn_dir direction.
        Returns (exit_n, exit_e, exit_track, arc_flown).
        """
        nonlocal total_time

        num_steps = max(10, int(arc_degrees / angular_step_deg))

        for step in range(num_steps + 1):
            t = step / num_steps
            current_pa = _wrap_360(entry_pa + turn_dir * arc_degrees * t)

            pos_rad = math.radians(current_pa)
            n = center_n + turn_radius_ft * math.cos(pos_rad)
            e = center_e + turn_radius_ft * math.sin(pos_rad)

            # Track is tangent to circle
            track_deg = _wrap_360(current_pa + turn_dir * 90)

            gs_fps = add_point(n, e, track_deg, bank_angle_deg * turn_dir, segment)

            if step > 0:
                arc_len = turn_radius_ft * math.radians(arc_degrees / num_steps)
                total_time += arc_len / gs_fps

        final_pa = _wrap_360(entry_pa + turn_dir * arc_degrees)
        final_n = center_n + turn_radius_ft * math.cos(math.radians(final_pa))
        final_e = center_e + turn_radius_ft * math.sin(math.radians(final_pa))
        final_track = _wrap_360(final_pa + turn_dir * 90)

        return final_n, final_e, final_track, arc_degrees

    for eight_num in range(num_eights):
        # ===== PYLON 1: Arc of arc_extent_deg degrees =====
        exit_n, exit_e, exit_track, arc_flown = generate_arc(
            p1_n, p1_e, p1_entry_pa, arc_extent_deg, p1_turn_dir,
            "pylon_1"
        )
        arc_degrees_flown.append(("P1", arc_flown))

        # ===== TRANSITION 1→2: Blend track from P1 exit to P2 entry =====
        trans_track, trans_time, trans_dist = generate_transition(
            exit_n, exit_e, exit_track,
            p2_entry_n, p2_entry_e, p2_entry_track,
            "transition_1_to_2"
        )
        transition_times.append(trans_time)
        transition_distances.append(trans_dist)

        # ===== PYLON 2: Arc of arc_extent_deg degrees (OPPOSITE turn) =====
        exit_n, exit_e, exit_track, arc_flown = generate_arc(
            p2_n, p2_e, p2_entry_pa, arc_extent_deg, p2_turn_dir,
            "pylon_2"
        )
        arc_degrees_flown.append(("P2", arc_flown))

        # ===== TRANSITION 2→1: Blend track from P2 exit to P1 entry =====
        trans_track, trans_time, trans_dist = generate_transition(
            exit_n, exit_e, exit_track,
            p1_entry_n, p1_entry_e, p1_entry_track,
            "transition_2_to_1"
        )
        transition_times.append(trans_time)
        transition_distances.append(trans_dist)

    # =========================================================================
    # COMPILE RESULTS
    # =========================================================================

    avg_pa = (max_pa + min_pa) / 2
    no_wind_pa = compute_pivotal_altitude(tas_knots)

    # Calculate transition statistics
    avg_transition_time = sum(transition_times) / len(transition_times) if transition_times else 0
    avg_transition_dist = sum(transition_distances) / len(transition_distances) if transition_distances else 0

    # ACS COMPLIANCE CHECKS
    # Per FAA-H-8083-3C and Commercial Pilot ACS:
    # - Pylon distance: 0.5 to 1.0 NM recommended (3000-6000 ft)
    # - Transition time: 3-5 seconds between pylons is typical for proper setup

    # Pylon distance check
    ACS_MIN_PYLON_DIST_FT = 3000.0  # ~0.5 NM
    ACS_MAX_PYLON_DIST_FT = 6000.0  # ~1.0 NM
    ACS_MIN_TRANSITION_SEC = 3.0
    ACS_MAX_TRANSITION_SEC = 5.0

    pylon_distance_warning = None
    if pylon_dist_ft < ACS_MIN_PYLON_DIST_FT:
        pylon_distance_warning = f"Pylons too close ({pylon_dist_nm:.2f} NM). ACS recommends 0.5-1.0 NM"
    elif pylon_dist_ft > ACS_MAX_PYLON_DIST_FT:
        pylon_distance_warning = f"Pylons too far apart ({pylon_dist_nm:.2f} NM). ACS recommends 0.5-1.0 NM"

    transition_time_warning = None
    if avg_transition_time < ACS_MIN_TRANSITION_SEC:
        transition_time_warning = f"Transition time too short ({avg_transition_time:.1f}s). Increase pylon distance or reduce speed"
    elif avg_transition_time > ACS_MAX_TRANSITION_SEC:
        transition_time_warning = f"Transition time long ({avg_transition_time:.1f}s). Decrease pylon distance or increase speed"

    warnings["pylon_distance_ft"] = round(pylon_dist_ft, 0)
    warnings["pylon_distance_nm"] = round(pylon_dist_nm, 2)
    warnings["turn_radius_ft"] = round(turn_radius_ft, 0)
    warnings["pylon_axis_deg"] = round(pylon_axis_deg, 0)

    # Transition timing (ACS requirement)
    warnings["transition_time_avg_sec"] = round(avg_transition_time, 1)
    warnings["transition_dist_avg_ft"] = round(avg_transition_dist, 0)
    warnings["pylon_distance_warning"] = pylon_distance_warning
    warnings["transition_time_warning"] = transition_time_warning

    # Arc statistics
    if arc_degrees_flown:
        warnings["p1_arc_degrees"] = round(arc_degrees_flown[0][1], 0) if arc_degrees_flown else 180
        warnings["p2_arc_degrees"] = round(arc_degrees_flown[1][1], 0) if len(arc_degrees_flown) > 1 else 180

    warnings["max_bank_achieved"] = round(max_bank, 1)
    warnings["min_bank_achieved"] = round(min_bank, 1) if min_bank < 90 else 0.0
    warnings["max_groundspeed"] = round(max_gs, 1)
    warnings["min_groundspeed"] = round(min_gs, 1)

    warnings["pivotal_alt_max"] = round(max_pa, 0)
    warnings["pivotal_alt_min"] = round(min_pa, 0)
    warnings["pivotal_alt_avg"] = round(avg_pa, 0)
    warnings["pivotal_alt_range"] = round(max_pa - min_pa, 0)
    warnings["pivotal_alt_no_wind"] = round(no_wind_pa, 0)

    warnings["total_time_sec"] = round(total_time, 1)
    warnings["weight_lb"] = round(weight_lb, 0)
    warnings["tas_knots"] = round(tas_knots, 1)
    warnings["ias_knots"] = round(ias_knots, 1)
    warnings["stall_speed_clean"] = round(stall_speed_clean, 1)
    warnings["maneuvering_speed"] = round(maneuvering_speed, 1)
    warnings["density_altitude_ft"] = round(pressure_alt_ft, 0)
    warnings["wind_dir"] = round(wind_dir_deg, 0)
    warnings["wind_speed"] = round(wind_speed_kt, 0)
    warnings["entry_direction"] = entry_direction
    warnings["bank_angle_target"] = round(bank_angle_deg, 0)

    return path, hover, warnings
