"""
S-Turn simulation module.

S-turns are a ground reference maneuver where the aircraft's ground track
resembles two opposite but equal half-circles on each side of a selected
straight-line ground reference (road, river, railroad track).

Reference: FAA Airplane Flying Handbook (FAA-H-8083-3C), Chapter 7

Key characteristics:
- Entry: Downwind, perpendicular (90°) to the reference line
- Altitude: 600-1000 ft AGL (constant throughout)
- Airspeed: Constant IAS throughout
- Ground track: Equal-radius semicircles on each side of the line
- Bank angle varies with groundspeed:
  - Maximum bank (30-45°, never exceed 45°) when crossing downwind
  - Minimum bank at the upwind 180° point
  - Wings level when crossing the reference line
- Wind compensation: Steeper bank downwind, shallower bank upwind
"""
import math
from geopy import Point as GeoPoint

from physics import (
    compute_pressure_altitude,
    compute_true_airspeed,
    compute_air_density,
    compute_load_factor,
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


def _interpolate_stall_speed(stall_data: dict, weight_lb: float, config: str = "clean") -> float:
    """
    Interpolate stall speed from aircraft stall_speeds data based on weight.

    Args:
        stall_data: Aircraft stall_speeds dict (e.g., {"clean": {"weights": [...], "speeds": [...]}})
        weight_lb: Current aircraft weight
        config: Flap configuration ("clean", "takeoff", "landing")

    Returns:
        Interpolated stall speed in KIAS
    """
    config_data = stall_data.get(config, stall_data.get("clean", {}))
    weights = config_data.get("weights", [])
    speeds = config_data.get("speeds", [])

    if not weights or not speeds or len(weights) != len(speeds):
        return 48.0  # Default fallback

    # If weight is below minimum, return minimum speed
    if weight_lb <= weights[0]:
        return float(speeds[0])

    # If weight is above maximum, return maximum speed
    if weight_lb >= weights[-1]:
        return float(speeds[-1])

    # Linear interpolation
    for i in range(len(weights) - 1):
        if weights[i] <= weight_lb <= weights[i + 1]:
            w_ratio = (weight_lb - weights[i]) / (weights[i + 1] - weights[i])
            return speeds[i] + w_ratio * (speeds[i + 1] - speeds[i])

    return float(speeds[-1])


def _get_stall_speed_for_weight(ac: dict, weight_lb: float, flap_config: str = "clean") -> float:
    """
    Get the stall speed adjusted for current weight.

    If aircraft has stall_speeds data, interpolate from that.
    Otherwise, use simple weight scaling from reference stall speed.
    """
    stall_data = ac.get("stall_speeds")
    if stall_data:
        return _interpolate_stall_speed(stall_data, weight_lb, flap_config)

    # Fallback: use single_engine_limits or default, then scale by weight
    sel = ac.get("single_engine_limits", {})
    vs_ref = sel.get("vs", sel.get("vs0", 48.0))

    # Weight scaling: Vs = Vs_ref * sqrt(W / W_ref)
    w_ref = _ref_weight_lb(ac)
    if w_ref and w_ref > 0 and weight_lb > 0:
        return float(vs_ref) * math.sqrt(weight_lb / w_ref)

    return float(vs_ref)


def _get_maneuvering_speed(ac: dict, weight_lb: float) -> float:
    """
    Get maneuvering speed (Va) adjusted for weight.
    Va = Va_ref * sqrt(W / W_max)
    """
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


def simulate_s_turn(
    reference_point: dict,
    line_bearing_deg: float,
    entry_side: str,
    turn_direction_first: str,
    altitude_ft: float = 800.0,
    ias_knots: float = 100.0,
    base_bank_deg: float = 35.0,
    num_s_turns: int = 2,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    oat_c: float = 15.0,
    altimeter_inhg: float = 29.92,
    field_elev_ft: float = 0.0,
    ac: dict = None,
    weight_lb: float = None,
    flap_config: str = "clean",
    power_setting: float = 0.5,
    cg_position: float = 0.5,
    timestep_sec: float = 0.25,
    # Post-2026-05-21 additions
    wind_profile=None,
    engine_option: str = None,
) -> tuple:
    """
    Simulate S-turns across a reference line with wind compensation.

    This is a GROUND REFERENCE maneuver - the aircraft maintains equal-radius
    semicircles on each side of the reference line regardless of wind.

    Args:
        reference_point: Dict with 'lat' and 'lon' - a point ON the reference line
        line_bearing_deg: Bearing of the reference line (0-360°, e.g., 90 = East-West line)
        entry_side: Which side to start from ('left' or 'right' of line when facing line_bearing)
        turn_direction_first: Direction of first turn ('left' or 'right')
        altitude_ft: Altitude in feet AGL (600-1000 typical)
        ias_knots: Indicated airspeed in knots
        base_bank_deg: Base bank angle used to calculate turn radius (30-45°)
        num_s_turns: Number of complete S-turns (each S = 2 semicircles)
        wind_dir_deg: Wind direction (FROM) in degrees
        wind_speed_kt: Wind speed in knots
        oat_c: Outside air temperature in Celsius
        altimeter_inhg: Altimeter setting in inches Hg
        field_elev_ft: Field elevation in feet MSL
        ac: Aircraft data dict (contains stall speeds, G limits, etc.)
        weight_lb: Current aircraft weight in pounds
        flap_config: Flap configuration ("clean", "takeoff", "landing")
        power_setting: Power setting as percentage (0.05=idle to 1.0=full power)
        cg_position: CG position as normalized value (0.0=forward, 0.5=mid, 1.0=aft)
        timestep_sec: Time step in seconds

    Returns:
        Tuple of (path, hover_data, warnings) where:
            - path: List of [lat, lon] coordinate pairs
            - hover_data: List of dicts containing flight telemetry
            - warnings: Dict with any warnings about the maneuver
    """
    if reference_point is None:
        return [], [], {}

    dt = float(timestep_sec) if timestep_sec and timestep_sec > 0 else 0.25

    # Parse and validate inputs
    altitude_ft = float(altitude_ft or 800.0)
    altitude_ft = max(400.0, min(1500.0, altitude_ft))
    ias_knots = float(ias_knots or 100.0)
    base_bank_deg = float(base_bank_deg or 35.0)
    base_bank_deg = max(20.0, min(45.0, base_bank_deg))
    wind_dir_deg = float(wind_dir_deg or 0.0)
    wind_speed_kt = float(wind_speed_kt or 0.0)
    oat_c = float(oat_c if oat_c is not None else 15.0)
    altimeter_inhg = float(altimeter_inhg if altimeter_inhg is not None else 29.92)
    field_elev_ft = float(field_elev_ft or 0.0)
    num_s_turns = max(1, int(num_s_turns or 2))
    line_bearing_deg = float(line_bearing_deg or 0.0)
    flap_config = str(flap_config or "clean").lower()

    # Parse power setting (0.05 = idle, 1.0 = full power)
    power_setting = float(power_setting) if power_setting is not None else 0.5
    power_setting = max(0.05, min(1.0, power_setting))

    # Parse CG position (0.0 = forward, 0.5 = mid, 1.0 = aft)
    cg_position = float(cg_position) if cg_position is not None else 0.5
    cg_position = max(0.0, min(1.0, cg_position))

    # Aircraft data defaults
    if ac is None:
        ac = {}

    # Honor user surface wind over the column's SFC layer (impossible-turn /
    # PO180 parity). S-turn is a single-altitude maneuver but the override
    # contract still applies so pilot edits aren't silently ignored.
    if wind_profile is not None:
        try:
            wind_profile = wind_profile.with_surface_override(
                wind_dir_deg, wind_speed_kt,
                surface_alt_ft_msl=field_elev_ft,
            )
            # Sample at the maneuver's altitude (600-1000 ft typical).
            wd, ws = wind_profile.at(field_elev_ft + altitude_ft)
            wind_dir_deg = float(wd)
            wind_speed_kt = float(ws)
        except Exception:
            pass

    # POH dynamics — required bank varies through each semicircle
    # (steeper downwind / shallower upwind); pre-fix snapped instantly
    # to the wind-corrected value each tick.
    try:
        from core.dynamics import dynamics_for
        pd_dyn = dynamics_for(ac) if ac else {}
    except Exception:
        pd_dyn = {}
    bank_response_tau_s = float(pd_dyn.get("bank_response_tau_s", 1.0))
    roll_rate_dps = float(pd_dyn.get("roll_rate_dps", 40.0))

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
        "original_bank": base_bank_deg,
        "effective_bank": base_bank_deg,
        "power_setting_pct": round(power_setting * 100, 0),
        "cg_position_pct": round(cg_position * 100, 0),
    }

    # Get aircraft performance limits
    stall_speed_base = _get_stall_speed_for_weight(ac, weight_lb, flap_config)

    # CG effect on stall speed:
    # Forward CG (0.0) requires more tail-down force, increasing effective wing loading
    # This raises stall speed by approximately 2-3%
    # Aft CG (1.0) reduces tail-down force, lowering stall speed by ~1-2%
    # Linear model: cg_factor = 1.0 + (0.5 - cg_position) * 0.04
    cg_stall_factor = 1.0 + (0.5 - cg_position) * 0.04
    stall_speed_clean = stall_speed_base * cg_stall_factor
    maneuvering_speed = _get_maneuvering_speed(ac, weight_lb)
    g_limit = _get_g_limit(ac, flap_config)

    # Check if requested IAS is safe
    # Minimum safe speed: 1.3 * Vs (stall margin for maneuvering)
    min_safe_ias = stall_speed_clean * 1.3

    if ias_knots < min_safe_ias:
        warnings["airspeed_warning"] = f"IAS {ias_knots:.0f} kt is below 1.3*Vs ({min_safe_ias:.0f} kt)"
        ias_knots = min_safe_ias  # Adjust to safe speed

    if ias_knots > maneuvering_speed:
        warnings["airspeed_warning"] = f"IAS {ias_knots:.0f} kt exceeds Va ({maneuvering_speed:.0f} kt) - limit bank to avoid overstress"

    # Calculate load factor for base bank angle
    base_load_factor = compute_load_factor(base_bank_deg)

    # Calculate stall speed in the turn: Vs_turn = Vs * sqrt(n)
    stall_speed_in_turn = stall_speed_clean * math.sqrt(base_load_factor)

    # Check if we have adequate stall margin in the turn
    stall_margin = ias_knots / stall_speed_in_turn
    if stall_margin < 1.2:
        warnings["stall_margin_warning"] = True
        # Reduce bank angle to maintain safe stall margin
        # Target margin of 1.3
        target_vs_turn = ias_knots / 1.3
        target_load_factor = (target_vs_turn / stall_speed_clean) ** 2
        if target_load_factor > 1.0:
            adjusted_bank = math.degrees(math.acos(1.0 / target_load_factor))
            adjusted_bank = max(15.0, min(adjusted_bank, base_bank_deg))
            warnings["bank_limited"] = True
            warnings["effective_bank"] = adjusted_bank
            base_bank_deg = adjusted_bank
            base_load_factor = compute_load_factor(base_bank_deg)

    # Check G limit
    if base_load_factor > g_limit:
        warnings["g_limit_warning"] = True
        # Reduce bank to stay within G limits
        adjusted_bank = math.degrees(math.acos(1.0 / g_limit))
        adjusted_bank = max(15.0, min(adjusted_bank, base_bank_deg))
        warnings["bank_limited"] = True
        warnings["effective_bank"] = adjusted_bank
        base_bank_deg = adjusted_bank
        base_load_factor = compute_load_factor(base_bank_deg)

    # Compute TAS from IAS using altitude and temperature
    alt_msl_ft = field_elev_ft + altitude_ft
    pressure_alt_ft = compute_pressure_altitude(alt_msl_ft, altimeter_inhg)
    density_alt_ft = compute_pressure_altitude(alt_msl_ft, altimeter_inhg)  # Simplified

    tas_knots = compute_true_airspeed(ias_knots, pressure_alt_ft, oat_c)
    tas_knots = float(tas_knots) if tas_knots and tas_knots > 1 else ias_knots
    tas_fps = tas_knots * 1.68781

    # Calculate air density for performance adjustments
    rho = compute_air_density(pressure_alt_ft, oat_c)
    rho_sl = 0.002377  # slugs/ft³ at sea level
    density_ratio = rho / rho_sl if rho > 0 else 1.0

    # Calculate turn radius from base bank angle and TAS (no-wind reference)
    # R = V² / (g * tan(bank))
    bank_rad = math.radians(base_bank_deg)
    turn_radius_ft = (tas_fps ** 2) / (G_FPS2 * math.tan(bank_rad))
    turn_radius_nm = turn_radius_ft / FT_PER_NM

    # Store radius info in warnings for display
    warnings["turn_radius_ft"] = round(turn_radius_ft, 0)
    warnings["turn_radius_nm"] = round(turn_radius_nm, 2)
    warnings["stall_speed_clean"] = round(stall_speed_clean, 1)
    warnings["stall_speed_in_turn"] = round(stall_speed_in_turn, 1)
    warnings["load_factor"] = round(base_load_factor, 2)
    warnings["tas_knots"] = round(tas_knots, 1)
    warnings["density_altitude_ft"] = round(pressure_alt_ft, 0)

    # Reference point on the line
    ref_lat = reference_point["lat"]
    ref_lon = reference_point["lon"]

    # Line direction vectors
    line_bearing_rad = math.radians(line_bearing_deg)
    line_unit_n = math.cos(line_bearing_rad)
    line_unit_e = math.sin(line_bearing_rad)

    # Perpendicular to line (pointing "left" when looking along line_bearing)
    perp_unit_n = -line_unit_e
    perp_unit_e = line_unit_n

    # Wind components (wind velocity in NE frame)
    wind_to_rad = math.radians((wind_dir_deg + 180.0) % 360.0)
    wind_fps = wind_speed_kt * 1.68781
    wn_fps = wind_fps * math.cos(wind_to_rad)
    we_fps = wind_fps * math.sin(wind_to_rad)

    # Entry side determines starting position
    if str(entry_side).lower().startswith('l'):
        entry_perp_sign = 1.0
    else:
        entry_perp_sign = -1.0

    # First turn direction
    first_turn_sign = -1.0 if str(turn_direction_first).lower().startswith('l') else 1.0

    # Initialize position: start one turn radius from line, perpendicular
    pos_n_ft = entry_perp_sign * turn_radius_ft * perp_unit_n
    pos_e_ft = entry_perp_sign * turn_radius_ft * perp_unit_e

    # Entry heading: perpendicular to entry direction, flying toward the line
    entry_heading_rad = math.atan2(-entry_perp_sign * perp_unit_e, -entry_perp_sign * perp_unit_n)
    hdg_deg = _wrap_360(math.degrees(entry_heading_rad))

    # Function to convert local position to lat/lon
    def local_to_latlon(n_ft, e_ft):
        lat = ref_lat + (n_ft / 364567.2)
        lon = ref_lon + (e_ft / (364567.2 * math.cos(math.radians(ref_lat))))
        return [lat, lon]

    # Function to compute signed cross-track distance from the reference line
    def cross_track_ft(n_ft, e_ft):
        return n_ft * perp_unit_n + e_ft * perp_unit_e

    # Initialize state
    path = []
    hover = []
    t = 0.0
    current_alt = altitude_ft  # Track altitude changes due to power setting

    total_semicircles = num_s_turns * 2
    current_semicircle = 0
    turn_sign = first_turn_sign
    prev_cross_track = cross_track_ft(pos_n_ft, pos_e_ft)
    angle_in_turn = 0.0

    # State machine
    APPROACH = 0
    TURNING = 1
    state = APPROACH

    # Track min/max values during maneuver
    max_bank_achieved = 0.0
    min_bank_achieved = 90.0
    max_gs = 0.0
    min_gs = 999.0
    min_alt = altitude_ft
    max_alt = altitude_ft
    # Post-2026-05-21 additions:
    # - bank_state_deg drives a τ-smoothed bank toward the wind-dictated
    #   required value each tick.
    # - peak_unclamped_bank tracks the geometric required bank BEFORE the
    #   45° / max_safe_bank clamp so the UI can show "geometry wanted N°".
    # - min_ias_achieved is the running minimum IAS so the result panel
    #   can show a real margin (callback referenced this key but the sim
    #   never set it).
    # - crossing_times collects times of each reference-line crossing so
    #   the scrubber can label them on the time slider.
    bank_state_deg = 0.0
    peak_unclamped_bank = 0.0
    min_ias_achieved = ias_knots
    crossing_times: list = []

    # Power setting effect on altitude maintenance:
    # In a banked turn, drag increases due to increased lift required
    # Higher power compensates, lower power results in altitude loss
    # At ~65% power, aircraft can typically maintain altitude in moderate turns
    # Below 65%, altitude loss is expected; above, slight climb possible
    power_balance_point = 0.65  # Power level for level flight in turns

    while current_semicircle < total_semicircles and t < 300:
        # Current cross track
        ct = cross_track_ft(pos_n_ft, pos_e_ft)

        # Compute ground track and groundspeed with wind
        hdg_rad = math.radians(hdg_deg)
        va_n = tas_fps * math.cos(hdg_rad)
        va_e = tas_fps * math.sin(hdg_rad)
        vg_n = va_n + wn_fps
        vg_e = va_e + we_fps
        gs_fps = math.hypot(vg_n, vg_e)
        gs_kt = gs_fps / 1.68781
        track_deg = _wrap_360(math.degrees(math.atan2(vg_e, vg_n)))
        drift_deg = _angle_diff_deg(track_deg, hdg_deg)

        # Track GS extremes
        if gs_kt > max_gs:
            max_gs = gs_kt
        if gs_kt < min_gs:
            min_gs = gs_kt

        # Determine bank angle and segment name
        if state == APPROACH:
            target_bank_deg = 0.0
            segment = "approach"
        else:
            # In a turn - bank varies with groundspeed for constant radius ground track
            required_centripetal = (gs_fps ** 2) / turn_radius_ft
            tan_bank = required_centripetal / G_FPS2
            geo_bank = math.degrees(math.atan(tan_bank))
            # Track geometric required bank BEFORE the safety clamp so we
            # can surface "wind-dictated geometry required N°" when the
            # clamp engages.
            if geo_bank > peak_unclamped_bank:
                peak_unclamped_bank = geo_bank

            # Hard 45° AOB cap (FAA ACS S-Turns standard — "bank not to
            # exceed 45° at maximum point"). Pre-fix the cap was the
            # smaller of `base_bank_deg × 1.2` or 45° — for entry banks
            # below 38° that effectively under-capped (a 30° base capped
            # the downwind bank at 36° instead of letting wind push it
            # toward the 45° ACS ceiling). Now the cap is always 45°
            # regardless of entry bank; the lower bound of 10° still
            # keeps the upwind crossings flyable.
            target_bank_deg = max(10.0, min(45.0, geo_bank))
            segment = f"turn_{current_semicircle + 1}"

        # Instant bank tracking for S-turn. Pre-fix did this; the audit
        # rewrite introduced τ-smoothing (POH bank_response_tau_s +
        # roll_rate_dps clamp), which is correct for energy maneuvers
        # where the pilot rolls TO a target and HOLDS it (chandelle,
        # steep turn, etc.). For ground-reference maneuvers like
        # S-turn, the pilot is continuously feedback-correcting bank
        # to maintain the planned ground-track radius — the τ lag
        # leaves the aircraft slightly off-axis when the turn
        # direction flips at each reference-line crossing, producing
        # visibly distorted semicircles. We still apply the
        # `roll_rate_dps × dt` physical clamp so a step change can't
        # exceed the airframe's actual roll capability (matters most
        # at the line crossing where target bank effectively reverses).
        delta_bank = target_bank_deg - bank_state_deg
        max_step = roll_rate_dps * dt
        if delta_bank > max_step:
            delta_bank = max_step
        elif delta_bank < -max_step:
            delta_bank = -max_step
        bank_state_deg += delta_bank
        bank_deg = bank_state_deg

        if state == TURNING:
            # Track bank extremes from the actually-flown bank.
            if bank_deg > max_bank_achieved:
                max_bank_achieved = bank_deg
            if bank_deg < min_bank_achieved:
                min_bank_achieved = bank_deg

        # Calculate current load factor for this bank angle
        current_load_factor = 1.0 / math.cos(math.radians(bank_deg)) if bank_deg < 90 else 1.0

        # Power setting effect on vertical speed:
        # Drag increases with load factor (roughly proportional to n)
        # If power is insufficient, aircraft loses altitude
        # Base descent rate at idle power in turn ≈ 500 fpm at max bank
        # Scale by (power_balance_point - power_setting) and load_factor
        if bank_deg > 5.0:
            # Extra drag from turn = (n - 1) factor
            drag_factor = current_load_factor - 1.0
            # Power deficit (negative means excess power)
            power_deficit = power_balance_point - power_setting
            # Vertical speed: positive deficit = descending
            # At idle (0.05) in 45° bank (n=1.41), expect ~400-500 fpm descent
            # At balance point (0.65), expect 0 fpm
            # Above balance point, slight climb possible
            vs_fpm = power_deficit * drag_factor * 1200.0  # Scale factor
            vs_fpm = max(-300.0, min(vs_fpm, 200.0))  # Limit to reasonable range
        else:
            # Wings level - minimal power effect
            power_deficit = 0.5 - power_setting
            vs_fpm = power_deficit * 100.0  # Small effect when wings level
            vs_fpm = max(-100.0, min(vs_fpm, 100.0))

        # Update altitude
        current_alt -= (vs_fpm / 60.0) * dt
        current_alt = max(0.0, current_alt)  # Don't go below ground

        # Track altitude extremes
        if current_alt < min_alt:
            min_alt = current_alt
        if current_alt > max_alt:
            max_alt = current_alt

        # Record position and data
        pos_latlon = local_to_latlon(pos_n_ft, pos_e_ft)
        path.append(pos_latlon)
        hover.append({
            "time": round(t, 2),
            "alt": round(current_alt, 1),
            "tas": round(tas_knots, 1),
            "ias": round(ias_knots, 1),
            "gs": round(gs_kt, 1),
            "aob": round(turn_sign * bank_deg, 1),  # Apply turn_sign for L/R display
            "vs": round(-vs_fpm, 0),  # Negative because vs_fpm is descent rate
            "track": round(track_deg, 1),
            "heading": round(hdg_deg, 1),
            "drift": round(drift_deg, 1),
            "load_factor": round(current_load_factor, 2),
            "segment": segment,
            "semicircle": current_semicircle + 1,
            "turn_progress": round(angle_in_turn, 1),
        })

        # Track min IAS — pre-fix the callback referenced `min_ias_achieved`
        # but the sim never emitted it. IAS is constant in this sim, but
        # surfacing the value lets the result panel display a real margin.
        if ias_knots < min_ias_achieved:
            min_ias_achieved = ias_knots

        # State transitions
        if state == APPROACH:
            if abs(ct) < 30.0:
                state = TURNING
                angle_in_turn = 0.0
        else:
            # In a turn - check for line crossing
            if angle_in_turn > 90.0:
                if (prev_cross_track > 0 and ct <= 0) or (prev_cross_track < 0 and ct >= 0):
                    # Record the time of each reference-line crossing for
                    # the scrubber marks.
                    crossing_times.append(round(t, 2))
                    current_semicircle += 1
                    if current_semicircle < total_semicircles:
                        turn_sign = -turn_sign
                        angle_in_turn = 0.0

        # Update heading based on state
        if state == TURNING:
            omega = gs_fps / turn_radius_ft
            turn_rate_dps = math.degrees(omega)
            hdg_deg = _wrap_360(hdg_deg + turn_sign * turn_rate_dps * dt)
            angle_in_turn += turn_rate_dps * dt

        # Move position based on ground velocity
        pos_n_ft += vg_n * dt
        pos_e_ft += vg_e * dt

        prev_cross_track = ct
        t += dt

    # Add final point
    if path:
        pos_latlon = local_to_latlon(pos_n_ft, pos_e_ft)
        if pos_latlon != path[-1]:
            path.append(pos_latlon)
            hdg_rad = math.radians(hdg_deg)
            va_n = tas_fps * math.cos(hdg_rad)
            va_e = tas_fps * math.sin(hdg_rad)
            vg_n = va_n + wn_fps
            vg_e = va_e + we_fps
            gs_fps = math.hypot(vg_n, vg_e)
            gs_kt = gs_fps / 1.68781
            track_deg = _wrap_360(math.degrees(math.atan2(vg_e, vg_n)))
            drift_deg = _angle_diff_deg(track_deg, hdg_deg)

            hover.append({
                "time": round(t, 2),
                "alt": round(current_alt, 1),
                "tas": round(tas_knots, 1),
                "ias": round(ias_knots, 1),
                "gs": round(gs_kt, 1),
                "aob": 0.0,
                "vs": 0,
                "track": round(track_deg, 1),
                "heading": round(hdg_deg, 1),
                "drift": round(drift_deg, 1),
                "load_factor": 1.0,
                "segment": "complete",
                "semicircle": total_semicircles,
                "turn_progress": 0.0,
            })

    # Add maneuver statistics to warnings
    warnings["max_bank_achieved"] = round(max_bank_achieved, 1)
    warnings["min_bank_achieved"] = round(min_bank_achieved, 1)
    warnings["max_groundspeed"] = round(max_gs, 1)
    warnings["min_groundspeed"] = round(min_gs, 1)
    warnings["total_time_sec"] = round(t, 1)
    warnings["weight_lb"] = round(weight_lb, 0)

    # Altitude tracking
    warnings["entry_altitude_ft"] = round(altitude_ft, 0)
    warnings["final_altitude_ft"] = round(current_alt, 0)
    warnings["min_altitude_ft"] = round(min_alt, 0)
    warnings["max_altitude_ft"] = round(max_alt, 0)
    warnings["altitude_loss_ft"] = round(altitude_ft - current_alt, 0)

    # Altitude warning if significant loss
    if altitude_ft - current_alt > 100:
        warnings["altitude_warning"] = f"Lost {round(altitude_ft - current_alt, 0):.0f} ft - increase power setting"

    # Post-2026-05-21 audit additions — fields the callback needs to render
    # a correct stall-margin chip and a peak-bank diagnostic.
    # Vs at the actually-flown max bank (post τ-smoothing).
    max_bank_for_vs = max(max_bank_achieved, 1.0)
    load_factor_at_max_bank = (
        1.0 / math.cos(math.radians(max_bank_for_vs))
        if max_bank_for_vs < 89.9 else float("inf")
    )
    vs_at_max_bank = (
        stall_speed_clean * math.sqrt(load_factor_at_max_bank)
        if math.isfinite(load_factor_at_max_bank) else None
    )
    warnings["min_ias_achieved"] = round(min_ias_achieved, 1)
    warnings["vs_clean_kt"] = round(stall_speed_clean, 1)
    warnings["vs_at_max_bank_kt"] = round(vs_at_max_bank, 1) if vs_at_max_bank else None
    warnings["peak_unclamped_bank_deg"] = round(peak_unclamped_bank, 1)
    warnings["roll_rate_dps_used"] = round(roll_rate_dps, 1)
    warnings["wind_profile_used"] = wind_profile is not None
    warnings["engine_option"] = engine_option
    warnings["crossing_times"] = list(crossing_times)

    return path, hover, warnings
