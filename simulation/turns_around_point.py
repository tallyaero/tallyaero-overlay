"""
Turns Around a Point simulation module.

Turns around a point is a ground reference maneuver where the aircraft maintains
a constant radius circular ground track around a fixed reference point while
compensating for wind by varying bank angle.

Reference: FAA Airplane Flying Handbook (FAA-H-8083-3C), Chapter 7

Key characteristics:
- Entry: Downwind, abeam the reference point at desired radius
- Altitude: 600-1000 ft AGL (constant throughout)
- Bank angle varies with groundspeed:
  - Maximum bank (up to 45°) when flying downwind (fastest groundspeed)
  - Minimum bank when flying upwind (slowest groundspeed)
- Ground track: Perfect circle around the reference point
- Complete at least one full 360° turn (preferably two or more)
- Maintain coordinated flight throughout

DESIGN PHILOSOPHY:
This simulation shows PERFECT execution - what the pilot should achieve.
The ground track IS the ideal circle. At each point, we calculate what
bank angle, heading, and other parameters are required to fly that perfect path.
This is for briefing/debriefing - showing the standard to aim for.
"""
import math

from physics import (
    compute_pressure_altitude,
    compute_true_airspeed,
    G_FPS2,
    FT_PER_NM,
)

from .base import _ref_weight_lb
from .eights_on_pylons import compute_pivotal_altitude


def _wrap_360(angle: float) -> float:
    """Normalize angle to [0, 360)."""
    return angle % 360.0


def _angle_diff_deg(a: float, b: float) -> float:
    """Compute signed difference (a - b), result in [-180, 180]."""
    diff = (a - b + 540.0) % 360.0 - 180.0
    return diff


def _interpolate_stall_speed(stall_data: dict, weight_lb: float, config: str = "clean") -> float:
    """Interpolate stall speed from aircraft stall_speeds data based on weight."""
    config_data = stall_data.get(config, stall_data.get("clean", {}))
    weights = config_data.get("weights", [])
    speeds = config_data.get("speeds", [])

    if not weights or not speeds or len(weights) != len(speeds):
        return 48.0

    if weight_lb <= weights[0]:
        return float(speeds[0])
    if weight_lb >= weights[-1]:
        return float(speeds[-1])

    for i in range(len(weights) - 1):
        if weights[i] <= weight_lb <= weights[i + 1]:
            w_ratio = (weight_lb - weights[i]) / (weights[i + 1] - weights[i])
            return speeds[i] + w_ratio * (speeds[i + 1] - speeds[i])

    return float(speeds[-1])


def _get_stall_speed_for_weight(ac: dict, weight_lb: float, flap_config: str = "clean") -> float:
    """Get the stall speed adjusted for current weight."""
    stall_data = ac.get("stall_speeds")
    if stall_data:
        return _interpolate_stall_speed(stall_data, weight_lb, flap_config)

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


def _get_g_limit(ac: dict, flap_config: str = "clean", category: str = "normal") -> float:
    """Get positive G limit for the aircraft configuration."""
    g_limits = ac.get("G_limits", {})
    cat_limits = g_limits.get(category, g_limits.get("normal", {}))
    config_limits = cat_limits.get(flap_config, cat_limits.get("clean", {}))
    return float(config_limits.get("positive", 3.8))


def simulate_turns_around_point(
    center_point: dict,
    turn_direction: str,
    entry_heading_deg: float = None,
    altitude_ft: float = 800.0,
    ias_knots: float = 100.0,
    orbit_radius_nm: float = 0.25,
    num_turns: int = 2,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    oat_c: float = 15.0,
    altimeter_inhg: float = 29.92,
    field_elev_ft: float = 0.0,
    ac: dict = None,
    weight_lb: float = None,
    power_setting: float = 0.5,
    cg_position: float = 0.5,
    angular_step_deg: float = 2.0,
    # Post-2026-05-21 additions
    wind_profile=None,
    engine_option: str = None,
) -> tuple:
    """
    Simulate PERFECT Turns Around a Point for briefing/debriefing.

    This generates the IDEAL ground track (a perfect circle) and calculates
    what bank angle, heading, groundspeed, etc. are required at each point
    to achieve that perfect execution.

    Args:
        center_point: Dict with 'lat' and 'lon' - the ground point to orbit around
        turn_direction: 'left' or 'right'
        entry_heading_deg: Entry heading (if None, calculated for downwind entry)
        altitude_ft: Altitude in feet AGL (600-1000 typical)
        ias_knots: Indicated airspeed in knots
        orbit_radius_nm: Desired orbit radius in nautical miles (typically 0.25 nm / ~1500 ft)
        num_turns: Number of complete 360° turns (minimum 1, typically 2)
        wind_dir_deg: Wind direction (FROM) in degrees
        wind_speed_kt: Wind speed in knots
        oat_c: Outside air temperature in Celsius
        altimeter_inhg: Altimeter setting in inches Hg
        field_elev_ft: Field elevation in feet MSL
        ac: Aircraft data dict
        weight_lb: Current aircraft weight in pounds
        power_setting: Power setting as percentage (0.05-1.0)
        cg_position: CG position (0.0=forward, 1.0=aft)
        angular_step_deg: Angular resolution for path points (degrees)

    Returns:
        Tuple of (path, hover_data, warnings) where:
            - path: List of [lat, lon] coordinate pairs forming a PERFECT circle
            - hover_data: List of dicts containing required flight parameters at each point
            - warnings: Dict with warnings and statistics
    """
    if center_point is None:
        return [], [], {}

    # Parse and validate inputs
    altitude_ft = float(altitude_ft or 800.0)
    altitude_ft = max(400.0, min(1500.0, altitude_ft))
    ias_knots = float(ias_knots or 100.0)
    orbit_radius_nm = float(orbit_radius_nm or 0.25)
    orbit_radius_nm = max(0.1, min(1.0, orbit_radius_nm))
    orbit_radius_ft = orbit_radius_nm * FT_PER_NM
    wind_dir_deg = float(wind_dir_deg or 0.0)
    wind_speed_kt = float(wind_speed_kt or 0.0)
    oat_c = float(oat_c if oat_c is not None else 15.0)
    altimeter_inhg = float(altimeter_inhg if altimeter_inhg is not None else 29.92)
    field_elev_ft = float(field_elev_ft or 0.0)
    num_turns = max(1, int(num_turns or 2))
    angular_step_deg = float(angular_step_deg) if angular_step_deg and angular_step_deg > 0 else 2.0

    # Turn direction: +1 for right (clockwise), -1 for left (counter-clockwise)
    turn_sign = -1.0 if str(turn_direction).lower().startswith('l') else 1.0

    # Parse power setting and CG
    power_setting = float(power_setting) if power_setting is not None else 0.5
    power_setting = max(0.05, min(1.0, power_setting))
    cg_position = float(cg_position) if cg_position is not None else 0.5
    cg_position = max(0.0, min(1.0, cg_position))

    # Aircraft data defaults
    if ac is None:
        ac = {}

    # User surface wind authoritative; column drives the per-tick wind
    # lookup. TAP is a single-altitude maneuver so we sample once at the
    # maneuver altitude. Pre-fix there was no wind_profile support at all.
    if wind_profile is not None:
        try:
            wind_profile = wind_profile.with_surface_override(
                wind_dir_deg, wind_speed_kt,
                surface_alt_ft_msl=field_elev_ft,
            )
            wd, ws = wind_profile.at(field_elev_ft + altitude_ft)
            wind_dir_deg = float(wd)
            wind_speed_kt = float(ws)
        except Exception:
            pass

    # Weight handling
    if weight_lb is None or weight_lb <= 0:
        weight_lb = ac.get("total_weight_lb")
        if weight_lb is None:
            weight_lb = _ref_weight_lb(ac) or 2300.0
    weight_lb = float(weight_lb)

    # Initialize warnings
    warnings = {
        "stall_margin_warning": False,
        "g_limit_warning": False,
        "airspeed_warning": None,
        "bank_limited": False,
        "max_bank_requested": 45.0,
        "power_setting_pct": round(power_setting * 100, 0),
        "cg_position_pct": round(cg_position * 100, 0),
    }

    # Get aircraft performance limits with CG adjustment
    stall_speed_base = _get_stall_speed_for_weight(ac, weight_lb, "clean")
    cg_stall_factor = 1.0 + (0.5 - cg_position) * 0.04
    stall_speed_clean = stall_speed_base * cg_stall_factor
    maneuvering_speed = _get_maneuvering_speed(ac, weight_lb)
    g_limit = _get_g_limit(ac, "clean")

    # Check if requested IAS is safe
    min_safe_ias = stall_speed_clean * 1.3
    if ias_knots < min_safe_ias:
        warnings["airspeed_warning"] = f"IAS {ias_knots:.0f} kt is below 1.3*Vs ({min_safe_ias:.0f} kt)"
        ias_knots = min_safe_ias

    if ias_knots > maneuvering_speed:
        warnings["airspeed_warning"] = f"IAS {ias_knots:.0f} kt exceeds Va ({maneuvering_speed:.0f} kt)"

    # Compute TAS from IAS
    alt_msl_ft = field_elev_ft + altitude_ft
    pressure_alt_ft = compute_pressure_altitude(alt_msl_ft, altimeter_inhg)
    tas_knots = compute_true_airspeed(ias_knots, pressure_alt_ft, oat_c)
    tas_knots = float(tas_knots) if tas_knots and tas_knots > 1 else ias_knots
    tas_fps = tas_knots * 1.68781

    # Wind vector (wind blowing TO direction, in NE frame)
    wind_to_deg = (wind_dir_deg + 180.0) % 360.0
    wind_to_rad = math.radians(wind_to_deg)
    wind_fps = wind_speed_kt * 1.68781
    wn_fps = wind_fps * math.cos(wind_to_rad)  # North component
    we_fps = wind_fps * math.sin(wind_to_rad)  # East component

    # Center point
    center_lat = center_point["lat"]
    center_lon = center_point["lon"]

    # Conversion factors for lat/lon
    ft_per_deg_lat = 364567.2
    ft_per_deg_lon = 364567.2 * math.cos(math.radians(center_lat))

    def local_to_latlon(n_ft, e_ft):
        """Convert local NE coordinates (relative to center) to lat/lon."""
        lat = center_lat + (n_ft / ft_per_deg_lat)
        lon = center_lon + (e_ft / ft_per_deg_lon)
        return [lat, lon]

    # Determine entry point angle (angle from center to entry point, in NE frame)
    # Standard entry is downwind, meaning aircraft is flying WITH the wind
    # So aircraft heading matches wind-to direction
    # Entry point is 90° perpendicular to entry heading

    # Downwind heading = direction wind is blowing TO
    downwind_heading = wind_to_deg

    # If no entry heading specified, use downwind
    if entry_heading_deg is None:
        entry_heading_deg = downwind_heading
    else:
        entry_heading_deg = float(entry_heading_deg)

    # Entry point is perpendicular to entry heading
    # For left turn: center is to the left, so entry point is to the right of center
    # For right turn: center is to the right, so entry point is to the left of center
    if turn_sign > 0:  # Right turn - center is to the right of aircraft
        entry_point_bearing = (entry_heading_deg - 90.0) % 360.0
    else:  # Left turn - center is to the left of aircraft
        entry_point_bearing = (entry_heading_deg + 90.0) % 360.0

    # Convert bearing to angle in NE frame (0=North=+Y, 90=East=+X)
    entry_angle_rad = math.radians(entry_point_bearing)

    # Initialize path and hover data
    path = []
    hover = []

    # Track statistics
    max_bank_achieved = 0.0
    min_bank_achieved = 90.0
    max_gs = 0.0
    min_gs = 999.0
    total_time = 0.0
    # Phase C1 — pivotal altitude varies with ground speed around the orbit.
    # TAP is flown at constant altitude, so the PA value is informational only
    # (it tells the pilot at what altitude this configuration would naturally
    # pivot — same physics as Eights on Pylons).
    max_pa = 0.0
    min_pa = 1e9
    pa_sum = 0.0
    pa_count = 0
    # Post-2026-05-21 audit additions:
    # - peak_unclamped_bank tracks geometry-required bank BEFORE the 45° clamp
    # - min_ias_achieved is constant in this sim (IAS is held) but emitted
    #   so the callback's margin chip uses a real value instead of a fallback
    # - turn_complete_times records the time at each completed 360° boundary
    #   so the scrubber can label them
    peak_unclamped_bank = 0.0
    min_ias_achieved = ias_knots
    turn_complete_times: list = []
    last_turn_number = 1

    # Generate points along the PERFECT circular path
    # We go around the circle, starting from the entry point
    total_angle_deg = num_turns * 360.0
    num_steps = int(total_angle_deg / angular_step_deg) + 1

    for step in range(num_steps):
        # Current angle around the circle (from entry point)
        progress_deg = step * angular_step_deg

        # Determine which turn we're on (1-indexed)
        turn_number = int(progress_deg / 360.0) + 1
        turn_progress_deg = progress_deg % 360.0

        # Absolute angle in NE frame
        # For right turn (clockwise): angle increases
        # For left turn (counter-clockwise): angle decreases
        if turn_sign > 0:  # Right turn
            current_angle_rad = entry_angle_rad + math.radians(progress_deg)
        else:  # Left turn
            current_angle_rad = entry_angle_rad - math.radians(progress_deg)

        # Position on the PERFECT circle (in local NE coordinates)
        pos_n_ft = orbit_radius_ft * math.cos(current_angle_rad)
        pos_e_ft = orbit_radius_ft * math.sin(current_angle_rad)

        # Ground track direction (tangent to circle)
        # Tangent is perpendicular to radius
        # For right turn: track is 90° clockwise from radius direction
        # For left turn: track is 90° counter-clockwise from radius direction
        radius_bearing_deg = _wrap_360(math.degrees(current_angle_rad))
        track_deg = _wrap_360(radius_bearing_deg + turn_sign * 90.0)
        track_rad = math.radians(track_deg)

        # Ground track unit vector
        track_n = math.cos(track_rad)
        track_e = math.sin(track_rad)

        # To maintain the perfect circular ground track, we need to calculate
        # what groundspeed results from flying with a certain heading into the wind

        # Wind component along track (positive = tailwind, helps groundspeed)
        wind_along_track = wn_fps * track_n + we_fps * track_e

        # Wind component across track (positive = wind pushing from left)
        wind_across_track = -wn_fps * track_e + we_fps * track_n

        # To maintain track, aircraft must crab into the crosswind
        # The aircraft's velocity through the air + wind = ground velocity along track
        #
        # If we define:
        #   - crab angle positive when aircraft heading is right of track
        #   - TAS_along_track = TAS * cos(crab)
        #   - TAS_across_track = TAS * sin(crab) (positive = aircraft pointing right of track)
        #
        # For the aircraft to track along the desired ground track:
        #   TAS_across_track + wind_across_track = 0
        #   TAS * sin(crab) = -wind_across_track
        #   crab = arcsin(-wind_across_track / TAS)

        cross_ratio = wind_across_track / max(tas_fps, 50.0)
        cross_ratio = max(-0.95, min(0.95, cross_ratio))  # Clamp to valid arcsin range
        crab_rad = math.asin(-cross_ratio)
        crab_deg = math.degrees(crab_rad)

        # Aircraft heading = track + crab
        hdg_deg = _wrap_360(track_deg + crab_deg)

        # Groundspeed along track
        # GS = TAS * cos(crab) + wind_along_track
        tas_along_track = tas_fps * math.cos(crab_rad)
        gs_fps = tas_along_track + wind_along_track
        gs_fps = max(10.0, gs_fps)  # Ensure positive
        gs_kt = gs_fps / 1.68781

        # Track GS extremes
        if gs_kt > max_gs:
            max_gs = gs_kt
        if gs_kt < min_gs:
            min_gs = gs_kt

        # Pivotal altitude at this ground speed (PA = GS² / 11.3 in ft AGL)
        pa_ft = compute_pivotal_altitude(gs_kt)
        if pa_ft > max_pa:
            max_pa = pa_ft
        if pa_ft < min_pa:
            min_pa = pa_ft
        pa_sum += pa_ft
        pa_count += 1

        # Required bank angle to maintain the constant radius at this groundspeed
        # Centripetal acceleration = GS² / R = g * tan(bank)
        # bank = arctan(GS² / (R * g))
        centripetal_accel = (gs_fps ** 2) / orbit_radius_ft
        tan_bank = centripetal_accel / G_FPS2
        bank_deg = math.degrees(math.atan(tan_bank))

        # Track peak geometric required bank BEFORE the 45° clamp so the
        # callback can surface "geometry needed N° (capped at 45)" when
        # the clamp engages.
        if bank_deg > peak_unclamped_bank:
            peak_unclamped_bank = bank_deg

        # Clamp bank to safe limits (max 45° per FAA standards for this maneuver)
        original_bank = bank_deg
        bank_deg = max(5.0, min(45.0, bank_deg))
        if original_bank > 45.0:
            warnings["bank_limited"] = True

        # Track bank extremes
        if bank_deg > max_bank_achieved:
            max_bank_achieved = bank_deg
        if bank_deg < min_bank_achieved:
            min_bank_achieved = bank_deg

        # Load factor at this bank angle
        load_factor = 1.0 / math.cos(math.radians(bank_deg)) if bank_deg < 89 else 10.0

        # Check stall margin at this bank
        stall_speed_in_turn = stall_speed_clean * math.sqrt(load_factor)
        if ias_knots / stall_speed_in_turn < 1.2:
            warnings["stall_margin_warning"] = True

        if load_factor > g_limit:
            warnings["g_limit_warning"] = True

        # Drift angle (difference between track and heading)
        drift_deg = _angle_diff_deg(track_deg, hdg_deg)

        # Time calculation: distance along arc / groundspeed
        if step > 0:
            arc_length_ft = orbit_radius_ft * math.radians(angular_step_deg)
            segment_time = arc_length_ft / gs_fps
            total_time += segment_time

        # Detect 360° boundary crossings for the scrubber phase marks.
        if turn_number != last_turn_number:
            turn_complete_times.append(round(total_time, 2))
            last_turn_number = turn_number

        # Track min IAS (constant in this sim, but surface it so callback
        # uses a real value).
        if ias_knots < min_ias_achieved:
            min_ias_achieved = ias_knots

        # Convert position to lat/lon
        pos_latlon = local_to_latlon(pos_n_ft, pos_e_ft)
        path.append(pos_latlon)

        # Hover data for this point (apply turn_sign to bank for L/R display)
        hover.append({
            "time": round(total_time, 2),
            "alt": round(altitude_ft, 1),
            "tas": round(tas_knots, 1),
            "ias": round(ias_knots, 1),
            "gs": round(gs_kt, 1),
            "aob": round(turn_sign * bank_deg, 1),
            "vs": 0,  # Perfect execution = constant altitude
            "track": round(track_deg, 1),
            "heading": round(hdg_deg, 1),
            "drift": round(drift_deg, 1),
            "load_factor": round(load_factor, 2),
            "turn_number": turn_number,
            "turn_progress": round(turn_progress_deg, 1),
            "segment": f"turn_{turn_number}",
            "wind_correction": round(crab_deg, 1),
            "pivotal_alt": round(pa_ft, 0),
        })

    # Compile statistics and warnings
    warnings["orbit_radius_ft"] = round(orbit_radius_ft, 0)
    warnings["orbit_radius_nm"] = round(orbit_radius_nm, 2)
    warnings["max_bank_achieved"] = round(max_bank_achieved, 1)
    warnings["min_bank_achieved"] = round(min_bank_achieved, 1)
    warnings["max_groundspeed"] = round(max_gs, 1)
    warnings["min_groundspeed"] = round(min_gs, 1)
    warnings["total_time_sec"] = round(total_time, 1)
    warnings["weight_lb"] = round(weight_lb, 0)
    warnings["tas_knots"] = round(tas_knots, 1)
    warnings["stall_speed_clean"] = round(stall_speed_clean, 1)
    warnings["density_altitude_ft"] = round(pressure_alt_ft, 0)
    warnings["entry_altitude_ft"] = round(altitude_ft, 0)
    warnings["final_altitude_ft"] = round(altitude_ft, 0)  # Perfect = no loss
    warnings["min_altitude_ft"] = round(altitude_ft, 0)
    warnings["altitude_loss_ft"] = 0  # Perfect execution

    # Pivotal-altitude summary (Phase C1 — ACS Gap 1).
    if pa_count > 0:
        warnings["pivotal_alt_min"] = round(min_pa, 0)
        warnings["pivotal_alt_max"] = round(max_pa, 0)
        warnings["pivotal_alt_avg"] = round(pa_sum / pa_count, 0)
        warnings["pivotal_alt_range"] = round(max_pa - min_pa, 0)

    # Entry point info
    warnings["entry_heading"] = round(entry_heading_deg, 0)
    warnings["wind_dir"] = round(wind_dir_deg, 0)
    warnings["wind_speed"] = round(wind_speed_kt, 0)

    # Post-2026-05-21 audit additions — fields the callback needs to
    # render a correct stall-margin chip and a peak-bank diagnostic.
    # Vs at the actual max bank flown (post 45° clamp).
    max_bank_for_vs = max(max_bank_achieved, 1.0)
    load_factor_at_max = (
        1.0 / math.cos(math.radians(max_bank_for_vs))
        if max_bank_for_vs < 89.9 else float("inf")
    )
    vs_at_max_bank = (
        stall_speed_clean * math.sqrt(load_factor_at_max)
        if math.isfinite(load_factor_at_max) else None
    )
    warnings["min_ias_achieved"] = round(min_ias_achieved, 1)
    warnings["vs_clean_kt"] = round(stall_speed_clean, 1)
    warnings["vs_at_max_bank_kt"] = round(vs_at_max_bank, 1) if vs_at_max_bank else None
    warnings["stall_speed_in_turn"] = warnings["vs_at_max_bank_kt"]  # callback compat
    warnings["peak_unclamped_bank_deg"] = round(peak_unclamped_bank, 1)
    warnings["wind_profile_used"] = wind_profile is not None
    warnings["engine_option"] = engine_option
    warnings["turn_complete_times"] = list(turn_complete_times)

    return path, hover, warnings
