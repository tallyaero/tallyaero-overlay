"""
Impossible turn simulation module.
"""
import math
from geopy.distance import distance

from physics import (
    compute_pressure_altitude, compute_air_density, compute_true_airspeed,
    compute_glide_ratio, adjust_glide_ratio_for_density, compute_load_factor,
    G_FPS2, FT_PER_NM, DEFAULT_ALIGN_WINDOW_DEG,
    point_from, calculate_initial_compass_bearing,
    _wrap_360, _angle_diff_deg, _heading_from_track_components,
    _wind_components_from_dir, _cross_track_to_centerline_ft
)

from .base import (
    _canon_flap_config, _canon_prop_config, _get_best_glide_and_ratio
)


# === Phase Constants ===
PHASE_TAKEOFF = "takeoff"
PHASE_CLIMB = "climb"
PHASE_REACTION = "reaction"
PHASE_TURN1 = "turn1"
PHASE_STRAIGHT = "straight"
PHASE_TURN2 = "turn2"
PHASE_FINAL = "final"

# === Slip Constants ===
SLIP_GR_REDUCTION = 0.4  # Slip can reduce glide ratio by up to 40%
SLIP_MIN_GR = 3.0  # Minimum effective glide ratio with slip


def _calculate_slip_for_touchdown(
    current_altitude_ft: float,
    distance_to_touchdown_ft: float,
    straight_glide_ratio: float,
) -> tuple:
    """
    Calculate slip intensity needed to hit the touchdown point exactly.

    Returns: (slip_intensity 0-1, effective_glide_ratio)

    Key insight: We need to arrive at touchdown point with ~0 altitude.
    - Required GR = distance / altitude (the GR we NEED to glide)
    - If straight_gr > required_gr, we'd overshoot, so we need to slip
    - Slip intensity proportional to how much we need to steepen descent
    """
    if current_altitude_ft <= 0 or distance_to_touchdown_ft <= 0:
        return 0.0, straight_glide_ratio

    # What GR do we need to exactly hit the touchdown point?
    required_gr = distance_to_touchdown_ft / current_altitude_ft

    # If we need better GR than we have, we can't make it (no slip needed)
    if required_gr >= straight_glide_ratio:
        return 0.0, straight_glide_ratio

    # We're high - need to slip to reduce effective GR
    min_slip_gr = straight_glide_ratio * (1.0 - SLIP_GR_REDUCTION)
    min_slip_gr = max(SLIP_MIN_GR, min_slip_gr)

    # If even full slip won't get us down, use full slip
    if required_gr <= min_slip_gr:
        return 1.0, min_slip_gr

    # Calculate proportional slip intensity
    gr_range = straight_glide_ratio - min_slip_gr
    gr_reduction_needed = straight_glide_ratio - required_gr
    slip_intensity = gr_reduction_needed / gr_range if gr_range > 0 else 0.0
    slip_intensity = max(0.0, min(1.0, slip_intensity))

    # Calculate effective GR
    effective_gr = straight_glide_ratio * (1.0 - slip_intensity * SLIP_GR_REDUCTION)
    effective_gr = max(SLIP_MIN_GR, effective_gr)

    return slip_intensity, effective_gr


def _get_stall_speed(ac: dict, weight_lbs: float, config: str = "clean") -> float:
    """Get stall speed adjusted for weight."""
    stall_speeds = ac.get("stall_speeds", {})
    config_data = stall_speeds.get(config, stall_speeds.get("clean", {}))

    weights = config_data.get("weights", [2000])
    speeds = config_data.get("speeds", [50])

    if not weights or not speeds:
        return 50.0  # Default fallback

    # Interpolate for weight
    if weight_lbs <= weights[0]:
        return float(speeds[0])
    if weight_lbs >= weights[-1]:
        return float(speeds[-1])

    for i in range(len(weights) - 1):
        if weights[i] <= weight_lbs <= weights[i + 1]:
            ratio = (weight_lbs - weights[i]) / (weights[i + 1] - weights[i])
            return speeds[i] + ratio * (speeds[i + 1] - speeds[i])

    return float(speeds[-1])


def _get_engine_hp(ac: dict, engine_option: str = None) -> float:
    """Get engine horsepower from aircraft data."""
    engines = ac.get("engine_options", {})
    if engine_option and engine_option in engines:
        return float(engines[engine_option].get("horsepower", 150))
    # Return first engine's HP or default
    for eng_data in engines.values():
        return float(eng_data.get("horsepower", 150))
    return 150.0


def _calculate_rate_of_climb(ac: dict, weight_lbs: float, density_alt_ft: float, engine_option: str = None) -> float:
    """
    Calculate rate of climb at Vy.

    Uses engine HP and typical performance to estimate ROC.
    Adjusts for weight and density altitude.

    Returns: ROC in feet per minute
    """
    engine_hp = _get_engine_hp(ac, engine_option)

    # Base ROC by horsepower (empirical approximation)
    if engine_hp >= 300:
        base_roc = 1200  # High performance (Bonanza, Cirrus SR22T, etc.)
    elif engine_hp >= 200:
        base_roc = 1000  # Mid-high (182, SR22, etc.)
    elif engine_hp >= 160:
        base_roc = 800   # Mid-range (Archer, 172S, etc.)
    else:
        base_roc = 650   # Trainer (152, older 172, etc.)

    # Weight adjustment: lighter = better climb
    max_wt = ac.get("max_weight", weight_lbs)
    if weight_lbs > 0 and max_wt > 0:
        weight_factor = math.sqrt(max_wt / weight_lbs)
        weight_factor = min(1.3, max(0.7, weight_factor))  # Clamp to reasonable range
    else:
        weight_factor = 1.0

    # Density altitude adjustment: ~3% loss per 1000 ft DA
    da_factor = max(0.3, 1.0 - (density_alt_ft * 0.00003))

    return base_roc * weight_factor * da_factor


def simulate_takeoff_phase(
    threshold_point: dict,
    heading_deg: float,
    ac: dict,
    weight_lbs: float,
    oat_c: float,
    altimeter_inhg: float,
    field_elev_ft: float,
    wind_dir: float,
    wind_speed: float,
    timestep_sec: float = 0.5,
    engine_option: str = None,
) -> tuple:
    """
    Simulate ground roll from brake release to liftoff.

    Physics:
    - Acceleration based on power-to-weight ratio, adjusted for density altitude
    - Liftoff at V_lof = 1.1 * Vs0
    - Ground track follows runway heading (no wind drift on ground)
    - Headwind reduces ground roll distance (higher effective IAS at lower groundspeed)

    Returns: (liftoff_point, liftoff_speed_kias, liftoff_time, path_segment, hover_segment)
    """
    from geopy import Point as GeoPoint

    dt = float(timestep_sec) if timestep_sec and timestep_sec > 0 else 0.5

    # Get liftoff speed (1.1 * Vs0)
    vs0 = _get_stall_speed(ac, weight_lbs, "clean")
    v_lof_kias = vs0 * 1.1

    # Get engine HP for acceleration estimate
    engine_hp = _get_engine_hp(ac, engine_option)

    # Calculate density altitude for power adjustment
    pressure_alt = compute_pressure_altitude(field_elev_ft, altimeter_inhg)
    # Approximate density altitude: PA + (120 * ISA deviation)
    # ISA temp at sea level = 15C, lapse rate = 2C/1000ft
    isa_temp = 15.0 - (pressure_alt * 0.002)  # ISA temp at this altitude
    isa_deviation = oat_c - isa_temp
    density_alt = pressure_alt + (120 * isa_deviation)

    # Base acceleration model: a = (T - D - friction) / m
    # More conservative model accounting for:
    # - Rolling friction (μ ≈ 0.02-0.03 on paved runway)
    # - Propeller efficiency at low speed
    # - Real-world POH ground roll distances
    # Typical GA: C172S ~960 ft ground roll at sea level, gross weight
    base_accel = (engine_hp / weight_lbs) * 28  # More conservative than before

    # Density altitude adjustment: power decreases ~3.5% per 1000 ft DA
    # This affects both engine power output and propeller efficiency
    da_factor = max(0.4, 1.0 - (density_alt * 0.000035))

    # Weight factor: heavier = slower acceleration (beyond the HP/weight ratio)
    # Also accounts for increased rolling friction with weight
    max_wt = ac.get("max_weight", weight_lbs)
    weight_ratio = weight_lbs / max_wt if max_wt > 0 else 1.0
    if weight_ratio > 1.0:
        # Overweight penalty - significant performance degradation
        weight_factor = 1.0 / (weight_ratio ** 1.5)
    elif weight_ratio > 0.85:
        # Near gross weight - slight penalty
        weight_factor = 1.0 - (weight_ratio - 0.85) * 0.3
    else:
        weight_factor = 1.0

    base_accel_kt_per_sec = base_accel * da_factor * weight_factor

    # Headwind/tailwind component
    wind_rad = math.radians(wind_dir)
    hdg_rad = math.radians(heading_deg)
    headwind_kt = wind_speed * math.cos(wind_rad - hdg_rad)  # Positive = headwind

    # Ground roll simulation
    path = []
    hover = []
    t = 0.0
    v_gs_kt = 0.0  # Ground speed
    v_ias_kt = 0.0  # Indicated airspeed (includes headwind effect)
    dist_ft = 0.0

    cur = GeoPoint(float(threshold_point["lat"]), float(threshold_point["lon"]))
    path.append([cur.latitude, cur.longitude])

    hover.append({
        "time": t,
        "phase": PHASE_TAKEOFF,
        "alt_agl": 0.0,
        "alt_msl": field_elev_ft,
        "ias": v_ias_kt,
        "tas": v_ias_kt,
        "gs": v_gs_kt,
        "vs": 0.0,
        "heading": heading_deg,
        "track": heading_deg,
        "bank": 0.0,
        "dist_from_threshold": 0.0,
    })

    while v_ias_kt < v_lof_kias and t < 60:  # Max 60 sec ground roll
        # Speed-dependent acceleration reduction
        # As speed increases: drag increases (V²), prop efficiency changes
        # At V_lof, acceleration is roughly 60% of initial
        speed_ratio = v_gs_kt / v_lof_kias if v_lof_kias > 0 else 0
        speed_factor = 1.0 - (0.4 * speed_ratio)  # Linear reduction to 60% at liftoff

        accel_kt_per_sec = base_accel_kt_per_sec * speed_factor

        # Update speeds
        v_gs_kt += accel_kt_per_sec * dt
        v_ias_kt = v_gs_kt + headwind_kt  # IAS includes headwind benefit

        # Update position (ground roll along runway)
        v_gs_fps = v_gs_kt * 1.68781  # kt to fps
        dist_delta_ft = v_gs_fps * dt
        dist_ft += dist_delta_ft

        # Move along heading
        cur = point_from(cur, heading_deg, dist_delta_ft / FT_PER_NM)

        t += dt
        path.append([cur.latitude, cur.longitude])

        hover.append({
            "time": t,
            "phase": PHASE_TAKEOFF,
            "alt_agl": 0.0,
            "alt_msl": field_elev_ft,
            "ias": v_ias_kt,
            "tas": v_ias_kt,
            "gs": v_gs_kt,
            "vs": 0.0,
            "heading": heading_deg,
            "track": heading_deg,
            "bank": 0.0,
            "dist_from_threshold": dist_ft / FT_PER_NM,
        })

    liftoff_point = {"lat": cur.latitude, "lon": cur.longitude}
    # Return ground roll distance (dist_ft) as 6th element
    return liftoff_point, v_ias_kt, t, path, hover, dist_ft


def simulate_climb_phase(
    start_point: dict,
    heading_deg: float,
    start_alt_agl: float,
    target_alt_agl: float,
    ac: dict,
    weight_lbs: float,
    oat_c: float,
    altimeter_inhg: float,
    field_elev_ft: float,
    wind_dir: float,
    wind_speed: float,
    timestep_sec: float = 0.5,
    engine_option: str = None,
    start_time: float = 0.0,
) -> tuple:
    """
    Simulate climb from liftoff to engine failure altitude.

    Physics:
    - Climb at Vy (from aircraft JSON)
    - ROC calculated from aircraft performance
    - Aircraft crabs into wind to maintain runway ground track
    - Ground track stays aligned with runway centerline (not heading)

    Returns: (failure_point, failure_heading, total_time, path_segment, hover_segment)
    """
    from geopy import Point as GeoPoint

    dt = float(timestep_sec) if timestep_sec and timestep_sec > 0 else 0.5

    # Get Vy from aircraft data
    vy_kias = ac.get("Vy", 75)

    # Calculate density altitude for ROC
    alt_msl = field_elev_ft + start_alt_agl
    pressure_alt = compute_pressure_altitude(alt_msl, altimeter_inhg)
    rho = compute_air_density(pressure_alt, oat_c)
    # Approximate density altitude using proper ISA deviation
    isa_temp = 15.0 - (pressure_alt * 0.002)  # ISA temp at this altitude
    isa_deviation = oat_c - isa_temp
    density_alt = pressure_alt + (120 * isa_deviation)

    # Calculate rate of climb
    roc_fpm = _calculate_rate_of_climb(ac, weight_lbs, density_alt, engine_option)

    # Calculate TAS from IAS
    tas_kias = compute_true_airspeed(vy_kias, pressure_alt, oat_c)

    # Wind components (north/east in fps)
    wn_fps, we_fps = _wind_components_from_dir(wind_dir, wind_speed)

    # Desired ground track = runway heading (maintain centerline)
    desired_track_deg = heading_deg  # We want to track along runway

    # Climb simulation
    path = []
    hover = []
    t = start_time
    alt_agl = start_alt_agl

    cur = GeoPoint(float(start_point["lat"]), float(start_point["lon"]))
    path.append([cur.latitude, cur.longitude])

    # Calculate wind correction angle (WCA) to maintain desired ground track
    # WCA = arcsin(crosswind_component / TAS)
    def calc_wca_and_gs(tas_fps, track_deg):
        """Calculate heading and ground speed to maintain track_deg ground track."""
        track_rad = math.radians(track_deg)
        # Crosswind component (perpendicular to desired track)
        # Positive crosswind from right requires left crab (positive WCA)
        w_cross = (-wn_fps * math.sin(track_rad)) + (we_fps * math.cos(track_rad))
        # Headwind component (along desired track, negative = headwind)
        w_head = (wn_fps * math.cos(track_rad)) + (we_fps * math.sin(track_rad))

        # WCA = arcsin(crosswind / TAS), clamped to valid range
        if tas_fps > 1.0:
            wca_ratio = max(-1.0, min(1.0, w_cross / tas_fps))
            wca_rad = math.asin(wca_ratio)
        else:
            wca_rad = 0.0

        # Heading to fly = track + WCA
        hdg = _wrap_360(track_deg + math.degrees(wca_rad))

        # Ground speed along track = TAS * cos(WCA) + headwind
        gs = tas_fps * math.cos(wca_rad) + w_head
        gs = max(1.0, gs)  # Ensure positive ground speed

        return hdg, gs, math.degrees(wca_rad)

    tas_fps = tas_kias * 1.68781  # kt to fps
    hdg, gs_fps, wca_deg = calc_wca_and_gs(tas_fps, desired_track_deg)
    gs_kias = gs_fps / 1.68781

    hover.append({
        "time": t,
        "phase": PHASE_CLIMB,
        "alt_agl": alt_agl,
        "alt_msl": field_elev_ft + alt_agl,
        "ias": vy_kias,
        "tas": tas_kias,
        "gs": gs_kias,
        "vs": roc_fpm,
        "heading": hdg,  # Crabbed heading
        "track": desired_track_deg,  # Actual ground track (runway heading)
        "bank": 0.0,
        "dist_from_threshold": 0.0,
        "wca": wca_deg,  # Wind correction angle
    })

    dist_from_liftoff_ft = 0.0

    while alt_agl < target_alt_agl and t < start_time + 300:  # Max 5 min climb
        # Update altitude
        alt_delta = (roc_fpm / 60.0) * dt  # ft per timestep
        alt_agl += alt_delta

        # Update position along desired ground track (runway centerline)
        dist_delta_ft = gs_fps * dt
        dist_from_liftoff_ft += dist_delta_ft

        # Move along runway ground track (not heading - we crab into wind)
        cur = point_from(cur, desired_track_deg, dist_delta_ft / FT_PER_NM)

        t += dt
        path.append([cur.latitude, cur.longitude])

        # Recalculate TAS and WCA at new altitude
        alt_msl = field_elev_ft + alt_agl
        pressure_alt = compute_pressure_altitude(alt_msl, altimeter_inhg)
        tas_kias = compute_true_airspeed(vy_kias, pressure_alt, oat_c)
        tas_fps = tas_kias * 1.68781

        # Recalculate heading correction for wind
        hdg, gs_fps, wca_deg = calc_wca_and_gs(tas_fps, desired_track_deg)
        gs_kias = gs_fps / 1.68781

        hover.append({
            "time": t,
            "phase": PHASE_CLIMB,
            "alt_agl": alt_agl,
            "alt_msl": field_elev_ft + alt_agl,
            "ias": vy_kias,
            "tas": tas_kias,
            "gs": gs_kias,
            "vs": roc_fpm,
            "heading": hdg,  # Crabbed heading
            "track": desired_track_deg,  # Actual ground track (runway heading)
            "bank": 0.0,
            "dist_from_threshold": dist_from_liftoff_ft / FT_PER_NM,
            "wca": wca_deg,
        })

    failure_point = {"lat": cur.latitude, "lon": cur.longitude}
    # Return the crabbed heading at failure point (aircraft pointing into wind)
    return failure_point, hdg, t, path, hover


def _run_impossible_turn_once(
    start_point,
    runway_heading_deg: float,
    turn_dir: str,
    bank_deg: float,
    reaction_sec: float,
    start_ias_kias: float,
    altitude_agl: float,
    align_window_deg: float,
    ac: dict,
    engine_option: str,
    weight_lbs: float,
    oat_c: float,
    altimeter_inhg: float,
    wind_dir: float,
    wind_speed: float,
    timestep_sec: float,
    flap_config: str = "clean",
    prop_config: str = "windmilling",
    touchdown_elev_ft: float = 0.0,
    min_turn_deg_before_capture: float = 190.0,
    centerline_xtol_ft: float = 60.0,  # ~half runway width, must land ON runway
    max_time_sec: float = 240.0,
    intercept_angle_deg: float = 25.0,
    xtrack_align_gate_ft: float = 800.0,  # Start final alignment earlier
    along_align_gate_ft: float = 2000.0,
    jink_bank_cap_deg: float = 40.0,  # More aggressive final alignment
    jink_hdg_tol_deg: float = 10.0,
    jink_xtrack_tol_ft: float = 60.0,  # Match centerline tolerance
    bank_response_tau_sec: float = 1.5,  # Faster bank response
    straight_track_bank_cap_deg: float = 20.0,  # More aggressive tracking in straight phase
    xtrack_intercept_scale_ft: float = 800.0,  # Tighter intercept scaling
    intercept_max_deg: float = 45.0,
    runway_threshold_point=None,  # NEW: Reference point for centerline (runway threshold)
):
    """Internal function to run a single impossible turn simulation.

    If runway_threshold_point is provided, centerline calculations use it as reference
    (for returning to actual runway). Otherwise, uses start_point (legacy behavior).
    """
    dt = float(timestep_sec) if timestep_sec and timestep_sec > 0 else 0.5

    _centerline_xtol_ft = float(centerline_xtol_ft)
    _align_window_deg = float(align_window_deg)

    runway_hdg = _wrap_360(float(runway_heading_deg))
    hdg = runway_hdg

    final_course_hdg = _wrap_360(runway_hdg + 180.0)

    # Centerline reference: use runway threshold if provided, otherwise start_point (legacy)
    centerline_ref = runway_threshold_point if runway_threshold_point is not None else start_point

    best_glide_kias, base_glide_ratio = _get_best_glide_and_ratio(ac, engine_option, flap_config, prop_config)
    flap_config = _canon_flap_config(flap_config)
    prop_config = _canon_prop_config(prop_config)
    gear_type = ac.get("gear_type", "fixed")

    alt_msl_ft = float(touchdown_elev_ft) + max(0.0, float(altitude_agl))
    pressure_alt_ft = compute_pressure_altitude(alt_msl_ft, float(altimeter_inhg))
    rho = compute_air_density(pressure_alt_ft, float(oat_c))

    straight_gr = compute_glide_ratio(base_glide_ratio, flap_config, gear_type, prop_config)
    straight_gr = adjust_glide_ratio_for_density(straight_gr, rho)
    straight_gr = max(3.0, min(straight_gr, 25.0))

    wn_fps, we_fps = _wind_components_from_dir(float(wind_dir), float(wind_speed))

    tau_sec = 4.0
    ias = float(start_ias_kias) if start_ias_kias and float(start_ias_kias) > 1 else best_glide_kias

    alt = float(altitude_agl)
    cur = start_point
    t = 0.0

    turn_dir = "left" if str(turn_dir).lower().startswith("l") else "right"
    sign_turn1 = -1.0 if turn_dir == "left" else 1.0
    sign_turn2 = -sign_turn1

    phase = "reaction"
    reaction_remaining = max(0.0, float(reaction_sec))

    total_turn_1 = 0.0
    total_turn_2 = 0.0

    best_miss = None
    best_abs_xtrack = None

    captured = False
    captured_at_time = None

    path = []
    hover = []

    bank_state_deg = 0.0
    max_slip_pct = 0.0  # Track maximum slip used

    def wind_corrected_heading_for_track(desired_track_deg: float, tas_fps: float) -> float:
        trk = math.radians(_wrap_360(desired_track_deg))
        w_cross = (-wn_fps * math.sin(trk)) + (we_fps * math.cos(trk))
        ratio = 0.0
        if tas_fps > 1.0:
            ratio = max(-1.0, min(1.0, w_cross / tas_fps))
        wca = math.asin(ratio)
        hdg_out = _wrap_360(desired_track_deg + math.degrees(wca))
        return hdg_out

    def record(gs_kt, aob_deg, vs_fpm, track_deg, drift_deg=None, slip_pct=0.0):
        hover.append({
            "time": float(t),
            "alt": float(max(0.0, alt)),
            "tas": float(tas),
            "gs": float(gs_kt),
            "aob": float(aob_deg),
            "vs": float(vs_fpm),
            "track": float(track_deg),
            "heading": float(hdg),
            "drift": float(drift_deg) if drift_deg is not None else None,
            "phase": phase,
            "slip_pct": float(slip_pct),
        })
        path.append([cur.latitude, cur.longitude])

    def _finalize_meta(success: bool, reason: str, impact_marker=None, xtrack_ft=None, along_ft=None, align_err_deg=None):
        m = {
            "success": bool(success),
            "impact_marker": impact_marker,
            "reason": str(reason),
            "bank_deg": float(bank_deg),
            "jink_bank_cap_deg": float(jink_bank_cap_deg),
            "time_sec": float(t),
            "end_alt_agl_ft": float(max(0.0, alt)),
            "best_xtrack_ft": float(best_abs_xtrack) if best_abs_xtrack is not None else None,
            "best_miss": best_miss,
            "captured": bool(captured),
            "captured_time_sec": float(captured_at_time) if captured_at_time is not None else None,
            "flap_config": str(flap_config),
            "prop_config": str(prop_config),
            "centerline_xtol_ft": _centerline_xtol_ft,
            "align_window_deg": _align_window_deg,
            "slip_used": max_slip_pct > 0,
            "slip_intensity_pct": float(max_slip_pct),
        }
        if xtrack_ft is not None:
            m["final_xtrack_ft"] = float(xtrack_ft)
        if along_ft is not None:
            m["final_along_ft"] = float(along_ft)
        if align_err_deg is not None:
            m["final_hdg_err_deg"] = float(align_err_deg)
        return m

    while t <= max_time_sec:
        ias += (best_glide_kias - ias) * min(1.0, dt / tau_sec)

        try:
            alt_msl = float(touchdown_elev_ft) + max(0.0, alt)
            palt = compute_pressure_altitude(alt_msl, float(altimeter_inhg))
            tas = compute_true_airspeed(float(ias), float(palt), float(oat_c))
            tas = float(tas) if tas and tas > 1 else float(ias)
        except Exception:
            tas = float(ias)

        tas_fps = tas * 1.68781

        xtrack_ft, along_ft = _cross_track_to_centerline_ft(centerline_ref, cur, final_course_hdg)
        if best_abs_xtrack is None or abs(float(xtrack_ft)) < best_abs_xtrack:
            best_abs_xtrack = abs(float(xtrack_ft))

        if phase == "turn1":
            desired_track_deg = None
            bank_target_deg = abs(float(bank_deg))
            sign = sign_turn1

        elif phase == "straight":
            intercept_offset = -max(-1.0, min(1.0, float(xtrack_ft) / float(xtrack_intercept_scale_ft))) * float(intercept_max_deg)
            desired_track_deg = _wrap_360(final_course_hdg + intercept_offset)
            bank_target_deg = None
            sign = 0.0

        elif phase == "turn2":
            # Turn2: actively track TOWARD centerline with aggressive correction
            # Much steeper intercept angle to overcome wind drift
            xtrack_correction = -max(-45.0, min(45.0, float(xtrack_ft) / 8.0))  # Very aggressive: 45° max
            desired_track_deg = _wrap_360(final_course_hdg + xtrack_correction)

            bank_target_deg = abs(float(jink_bank_cap_deg))  # Use full jink bank
            # Calculate correct turn direction based on track error
            track_err_to_desired = _angle_diff_deg(desired_track_deg, track_deg)
            if abs(track_err_to_desired) < 1.0:
                sign = 0.0  # Close enough
            elif track_err_to_desired > 0:
                sign = 1.0  # Turn right
            else:
                sign = -1.0  # Turn left

        elif phase == "final":
            desired_track_deg = final_course_hdg
            bank_target_deg = 0.0
            sign = 0.0

        else:
            desired_track_deg = None
            bank_target_deg = 0.0
            sign = 0.0

        if bank_response_tau_sec and bank_response_tau_sec > 0:
            alpha = min(1.0, dt / float(bank_response_tau_sec))
        else:
            alpha = 1.0

        if phase != "straight":
            bank_state_deg = bank_state_deg + (float(bank_target_deg) - bank_state_deg) * alpha

        aob = float(bank_state_deg)

        max_hdg_rate_dps = 12.0

        if abs(aob) > 0.1 and phase in ["turn1", "turn2", "straight"]:
            turn_rate_rps = (G_FPS2 * math.tan(math.radians(abs(aob)))) / max(1.0, tas_fps)
            turn_rate_dps = math.degrees(turn_rate_rps)
            dpsi = turn_rate_dps * dt
            if phase in ["turn1", "turn2"]:
                hdg = _wrap_360(hdg + sign * dpsi)
                if phase == "turn1":
                    total_turn_1 += dpsi
                else:
                    total_turn_2 += dpsi
        else:
            turn_rate_dps = 0.0

        hdg_rad = math.radians(hdg)
        va_n = tas_fps * math.cos(hdg_rad)
        va_e = tas_fps * math.sin(hdg_rad)

        vg_n = va_n + wn_fps
        vg_e = va_e + we_fps
        gs_fps = math.hypot(vg_n, vg_e)
        gs_kt = gs_fps / 1.68781
        track_deg = _heading_from_track_components(vg_n, vg_e)
        drift_deg = _angle_diff_deg(track_deg, hdg)
        align_err = abs(_angle_diff_deg(track_deg, final_course_hdg))

        if phase == "straight":
            # Intercept toward centerline: if xtrack>0 (right), turn left (negative offset)
            intercept_offset = -max(-1.0, min(1.0, float(xtrack_ft) / float(xtrack_intercept_scale_ft))) * float(intercept_max_deg)
            desired_track_deg = _wrap_360(final_course_hdg + intercept_offset)

            track_err = _angle_diff_deg(desired_track_deg, track_deg)
            k_bank = 0.35
            cmd = max(-float(straight_track_bank_cap_deg), min(float(straight_track_bank_cap_deg), k_bank * float(track_err)))
            bank_target_signed = float(cmd)

            bank_target_mag = abs(bank_target_signed)
            sign = -1.0 if bank_target_signed < 0 else (1.0 if bank_target_signed > 0 else 0.0)

            bank_state_deg = bank_state_deg + (bank_target_mag - bank_state_deg) * alpha
            aob = float(bank_state_deg)

            if abs(aob) > 0.1:
                turn_rate_rps = (G_FPS2 * math.tan(math.radians(abs(aob)))) / max(1.0, tas_fps)
                turn_rate_dps = math.degrees(turn_rate_rps)
                dpsi = turn_rate_dps * dt
                hdg = _wrap_360(hdg + sign * dpsi)

                hdg_rad = math.radians(hdg)
                va_n = tas_fps * math.cos(hdg_rad)
                va_e = tas_fps * math.sin(hdg_rad)
                vg_n = va_n + wn_fps
                vg_e = va_e + we_fps
                gs_fps = math.hypot(vg_n, vg_e)
                gs_kt = gs_fps / 1.68781
                track_deg = _heading_from_track_components(vg_n, vg_e)
                drift_deg = _angle_diff_deg(track_deg, hdg)
                align_err = abs(_angle_diff_deg(track_deg, final_course_hdg))

        if phase == "final":
            # In final phase, actively track toward centerline with banking if needed
            # Very aggressive intercept to overcome wind drift
            xtrack_correction_deg = -max(-45.0, min(45.0, float(xtrack_ft) / 8.0))  # Very aggressive: 45° max
            desired_track = _wrap_360(final_course_hdg + xtrack_correction_deg)

            # Calculate required heading for desired track
            hdg_cmd = wind_corrected_heading_for_track(desired_track, tas_fps)
            hdg_err = _angle_diff_deg(hdg_cmd, hdg)

            # Use bank to turn if heading error is significant
            if abs(hdg_err) > 3.0:
                # Bank up to 20° to correct heading
                bank_for_correction = max(-20.0, min(20.0, hdg_err * 0.8))
                bank_state_deg = bank_state_deg + (abs(bank_for_correction) - bank_state_deg) * alpha
                aob = float(bank_state_deg)
                turn_sign = 1.0 if hdg_err > 0 else -1.0

                if abs(aob) > 0.1:
                    turn_rate_rps = (G_FPS2 * math.tan(math.radians(abs(aob)))) / max(1.0, tas_fps)
                    turn_rate_dps = math.degrees(turn_rate_rps)
                    dpsi = turn_rate_dps * dt
                    hdg = _wrap_360(hdg + turn_sign * dpsi)
            else:
                # Small corrections via heading adjustment
                hdg_step = max(-max_hdg_rate_dps * dt, min(max_hdg_rate_dps * dt, hdg_err))
                hdg = _wrap_360(hdg + hdg_step)
                bank_state_deg = bank_state_deg * 0.8  # Relax bank

            hdg_rad = math.radians(hdg)
            va_n = tas_fps * math.cos(hdg_rad)
            va_e = tas_fps * math.sin(hdg_rad)
            vg_n = va_n + wn_fps
            vg_e = va_e + we_fps
            gs_fps = math.hypot(vg_n, vg_e)
            gs_kt = gs_fps / 1.68781
            track_deg = _heading_from_track_components(vg_n, vg_e)
            drift_deg = _angle_diff_deg(track_deg, hdg)
            align_err = abs(_angle_diff_deg(track_deg, final_course_hdg))

        if abs(aob) > 0.1:
            n = compute_load_factor(abs(aob))
            glide_eff = straight_gr / max(n, 1.0)
        else:
            glide_eff = straight_gr
        glide_eff = max(2.0, glide_eff)

        # Calculate slip for energy management
        # Distance to touchdown: use along_ft (negative = before threshold)
        # When along_ft < 0, we're approaching; when >= 0, we're at/past threshold
        dist_to_touchdown_ft = max(0.0, -along_ft) if along_ft < 0 else 0.0

        # Also add lateral distance for more accurate energy calc
        total_dist_to_touchdown_ft = math.hypot(dist_to_touchdown_ft, abs(xtrack_ft))

        # Calculate slip based on altitude vs distance to touchdown
        slip_intensity, slip_glide_ratio = _calculate_slip_for_touchdown(
            current_altitude_ft=alt,
            distance_to_touchdown_ft=total_dist_to_touchdown_ft,
            straight_glide_ratio=glide_eff,
        )

        # Apply slip to glide ratio if we're high
        if slip_intensity > 0.05:
            glide_eff = slip_glide_ratio

        slip_pct = round(slip_intensity * 100, 0)

        # Track maximum slip used
        if slip_pct > max_slip_pct:
            max_slip_pct = slip_pct

        vs_fps = tas_fps / glide_eff
        alt -= vs_fps * dt
        vs_fpm = vs_fps * 60.0

        record(
            gs_kt=gs_kt,
            aob_deg=(sign * aob if abs(aob) > 0.1 else 0.0),
            vs_fpm=vs_fpm,
            track_deg=track_deg,
            drift_deg=drift_deg,
            slip_pct=slip_pct,
        )

        if phase in ["turn2", "straight", "final"] or (phase == "turn1" and total_turn_1 >= float(min_turn_deg_before_capture)):
            behind_penalty = 20000.0 if along_ft <= 0.0 else 0.0
            miss_score = (
                abs(float(xtrack_ft)) +
                200.0 * abs(float(align_err)) +
                behind_penalty -
                0.5 * max(0.0, float(alt))
            )

            if best_miss is None or miss_score < best_miss["miss_score"]:
                best_miss = {
                    "miss_score": float(miss_score),
                    "xtrack_ft": float(xtrack_ft),
                    "align_err_deg": float(align_err),
                    "along_ft": float(along_ft),
                    "alt": float(max(0.0, alt)),
                    "time": float(t),
                    "phase": str(phase),
                }

        if alt <= 0.0:
            # Check if close enough to centerline to count as success (within ~75 ft)
            runway_success_tol_ft = 75.0
            close_enough = abs(xtrack_ft) <= runway_success_tol_ft

            if captured or close_enough:
                # Use touchdown point as marker location (will update if rollout added)
                marker_lat, marker_lon = cur.latitude, cur.longitude

                # If close to centerline, add smooth rollout to centerline for visualization
                if abs(xtrack_ft) > 5.0:  # Only if not already on centerline
                    # Calculate centerline point at current along position
                    # Add 2-3 points curving smoothly to centerline
                    rollout_dist_ft = min(500.0, abs(xtrack_ft) * 5)  # Rollout distance
                    steps = 3
                    for i in range(1, steps + 1):
                        frac = float(i) / steps
                        # Interpolate xtrack toward 0
                        interp_xtrack = xtrack_ft * (1.0 - frac)
                        # Move forward along final course
                        step_along = (rollout_dist_ft / steps) * i
                        # Calculate new position: move along final course + lateral offset
                        step_nm = step_along / FT_PER_NM
                        base_pt = point_from(cur, final_course_hdg, step_nm)
                        # Apply remaining lateral offset (perpendicular to final course)
                        perp_hdg = _wrap_360(final_course_hdg + (90.0 if interp_xtrack > 0 else -90.0))
                        offset_nm = abs(interp_xtrack) / FT_PER_NM
                        final_pt = point_from(base_pt, perp_hdg, offset_nm)
                        path.append([final_pt.latitude, final_pt.longitude])
                        hover.append({
                            "time": float(t + i * 0.5),
                            "alt": 0.0,
                            "tas": float(tas * 0.9),  # Slowing down
                            "gs": float(gs_kt * 0.9),
                            "aob": 0.0,
                            "vs": 0.0,
                            "track": float(final_course_hdg),
                            "heading": float(hdg),
                            "phase": "rollout",
                            "slip_pct": 0.0,
                        })
                    xtrack_ft = 0.0  # Now on centerline
                    # Update marker to end of rollout (on centerline)
                    marker_lat, marker_lon = path[-1][0], path[-1][1]

                return path, hover, _finalize_meta(
                    success=True,
                    reason="touchdown_after_capture" if captured else "touchdown_close_enough",
                    impact_marker=(marker_lat, marker_lon),
                    xtrack_ft=xtrack_ft,
                    along_ft=along_ft,
                    align_err_deg=align_err,
                )
            return path, hover, _finalize_meta(
                success=False,
                reason="impact",
                impact_marker=(cur.latitude, cur.longitude),
                xtrack_ft=xtrack_ft,
                along_ft=along_ft,
                align_err_deg=align_err,
            )

        if phase == "reaction":
            reaction_remaining -= dt
            if reaction_remaining <= 0.0:
                phase = "turn1"

        elif phase == "turn1":
            # Calculate intercept track - negative offset for positive xtrack (turn toward centerline)
            intercept_offset = -max(-1.0, min(1.0, float(xtrack_ft) / float(xtrack_intercept_scale_ft))) * float(intercept_max_deg)
            intercept_trk = _wrap_360(final_course_hdg + intercept_offset)
            intercept_err = abs(_angle_diff_deg(intercept_trk, track_deg))

            if total_turn_1 >= float(min_turn_deg_before_capture) and intercept_err <= float(intercept_angle_deg):
                phase = "straight"

        elif phase == "straight":
            # Check for capture: on centerline, aligned, and approaching/at runway
            # along_ft > -2000 allows capture while still approaching threshold
            if align_err <= float(align_window_deg) and abs(xtrack_ft) <= float(centerline_xtol_ft):
                captured = True
                if captured_at_time is None:
                    captured_at_time = float(t)
                phase = "final"
            else:
                # Transition to turn2 (final alignment jink) when:
                # 1. Close to centerline AND reasonably aligned (can complete jink)
                # 2. OR very close to centerline (forced alignment attempt)
                #
                # Note: We allow turn2 even if past the threshold - landing on the
                # extended centerline is still a "success" for the impossible turn.
                # The alternative is crashing off the runway.
                close_to_centerline = abs(xtrack_ft) <= float(xtrack_align_gate_ft)  # < 600 ft
                very_close = abs(xtrack_ft) <= float(centerline_xtol_ft) * 2  # < 300 ft
                reasonably_aligned = align_err <= float(intercept_angle_deg) * 1.5  # < ~37.5 deg

                # Transition when close and aligned enough to complete the alignment
                if very_close or (close_to_centerline and reasonably_aligned):
                    phase = "turn2"

        elif phase == "turn2":
            hdg_tol = min(float(align_window_deg), float(jink_hdg_tol_deg)) if float(jink_hdg_tol_deg) > 0 else float(align_window_deg)
            xtol = min(float(centerline_xtol_ft), float(jink_xtrack_tol_ft)) if float(jink_xtrack_tol_ft) > 0 else float(centerline_xtol_ft)

            # Capture when aligned and on centerline (regardless of along_ft)
            if align_err <= hdg_tol and abs(xtrack_ft) <= xtol:
                captured = True
                if captured_at_time is None:
                    captured_at_time = float(t)
                phase = "final"

            if abs(xtrack_ft) <= float(centerline_xtol_ft) and align_err <= float(align_window_deg):
                captured = True
                if captured_at_time is None:
                    captured_at_time = float(t)
                phase = "final"

        step_nm = (gs_fps * dt) / FT_PER_NM
        cur = point_from(cur, track_deg, step_nm)

        xtrack_ft, along_ft = _cross_track_to_centerline_ft(centerline_ref, cur, final_course_hdg)
        align_err = abs(_angle_diff_deg(track_deg, final_course_hdg))

        t += dt

    xtrack_ft, along_ft = _cross_track_to_centerline_ft(centerline_ref, cur, final_course_hdg)
    align_err = abs(_angle_diff_deg(track_deg, final_course_hdg)) if hover else None

    return path, hover, _finalize_meta(
        success=False,
        reason="timeout",
        impact_marker=(cur.latitude, cur.longitude),
        xtrack_ft=xtrack_ft,
        along_ft=along_ft,
        align_err_deg=align_err,
    )


def simulate_impossible_turn(
    start_point,
    runway_heading_deg: float,
    turn_dir: str,
    reaction_sec: float,
    start_ias_kias: float,
    altitude_agl: float,
    align_window_deg: float = DEFAULT_ALIGN_WINDOW_DEG,
    ac: dict = None,
    engine_option: str = None,
    weight_lbs: float = None,
    oat_c: float = None,
    altimeter_inhg: float = None,
    wind_dir: float = None,
    wind_speed: float = None,
    timestep_sec: float = 0.5,
    flap_config: str = "clean",
    prop_config: str = "windmilling",
    touchdown_elev_ft: float = 0.0,
    bank_min_deg: float = 15.0,
    bank_max_deg: float = 45.0,
    bank_step_deg: float = 1.0,
    intercept_angle_deg: float = 25.0,
    xtrack_align_gate_ft: float = 800.0,   # Start final alignment when close
    along_align_gate_ft: float = 2000.0,
    jink_bank_cap_deg: float = 40.0,   # Aggressive final alignment bank
    jink_hdg_tol_deg: float = 10.0,    # Heading tolerance for capture
    jink_xtrack_tol_ft: float = 60.0,  # Must be within ~half runway width
    find_min_alt: bool = True,
    min_alt_floor_agl: float = 300.0,  # More realistic floor (accounts for reaction, roll, alignment)
    max_alt_ceiling_agl: float = 2000.0,
    min_alt_resolution_ft: float = 10.0,
    # NEW: Takeoff/climb simulation parameters
    include_takeoff_climb: bool = False,
    threshold_point: dict = None,
    runway_length_ft: float = None,
):
    """
    Simulate impossible turn maneuver.

    When include_takeoff_climb=True, simulates full sequence:
    1. Takeoff roll from threshold_point along runway heading
    2. Climb at Vy from liftoff to altitude_agl (engine failure altitude)
    3. Turn-back maneuver after engine failure
    4. Glide back to runway

    When include_takeoff_climb=False (legacy mode), simulates from engine failure point only.

    Returns (path, hover, meta) where:
    - path: List of [lat, lon] coordinates
    - hover: List of telemetry dicts with phase, time, altitude, speeds, etc.
    - meta: Dict with success status, min_feasible_alt_agl, and phase-specific info
    """
    from geopy import Point as GeoPoint

    if ac is None:
        return [], [], {"success": False, "reason": "no_aircraft_data"}

    # Handle takeoff/climb mode vs legacy mode
    if include_takeoff_climb:
        if threshold_point is None:
            return [], [], {"success": False, "reason": "no_threshold_point"}
        # Use threshold as start for takeoff simulation
        actual_start_point = None  # Will be computed as failure point after climb
    else:
        if start_point is None:
            return [], [], {"success": False, "reason": "no_start_point"}
        actual_start_point = start_point

    runway_hdg = float(runway_heading_deg or 0.0)
    turn_dir = "left" if str(turn_dir).strip().lower().startswith("l") else "right"

    flap_config = _canon_flap_config(flap_config)
    prop_config = _canon_prop_config(prop_config)

    weight_lbs_f = float(weight_lbs or 0.0)
    oat_c_f = float(oat_c if oat_c is not None else 15.0)
    altimeter_inhg_f = float(altimeter_inhg if altimeter_inhg is not None else 29.92)
    wind_dir_f = float(wind_dir or 0.0)
    wind_speed_f = float(wind_speed or 0.0)
    timestep_f = float(timestep_sec) if timestep_sec and float(timestep_sec) > 0 else 0.5
    reaction_f = float(reaction_sec or 0.0)
    start_ias_f = float(start_ias_kias or 0.0)
    altitude_agl_f = float(altitude_agl or 0.0)
    align_window_f = float(align_window_deg if align_window_deg is not None else DEFAULT_ALIGN_WINDOW_DEG)
    touchdown_elev_f = float(touchdown_elev_ft or 0.0)

    if ac.get("engine_count", 1) > 1 and not engine_option:
        return [], [], {"success": False, "reason": "missing_engine_option_for_multiengine"}

    # === TAKEOFF/CLIMB SIMULATION (if enabled) ===
    takeoff_path = []
    takeoff_hover = []
    climb_path = []
    climb_hover = []
    takeoff_climb_time = 0.0
    glide_start_point = actual_start_point  # Will be GeoPoint
    runway_threshold_geopoint = None  # For centerline reference

    if include_takeoff_climb and threshold_point:
        # Create threshold GeoPoint for centerline reference
        runway_threshold_geopoint = GeoPoint(float(threshold_point["lat"]), float(threshold_point["lon"]))
        # Run takeoff simulation
        liftoff_point, liftoff_ias, liftoff_time, to_path, to_hover, ground_roll_ft = simulate_takeoff_phase(
            threshold_point=threshold_point,
            heading_deg=runway_hdg,
            ac=ac,
            weight_lbs=weight_lbs_f,
            oat_c=oat_c_f,
            altimeter_inhg=altimeter_inhg_f,
            field_elev_ft=touchdown_elev_f,
            wind_dir=wind_dir_f,
            wind_speed=wind_speed_f,
            timestep_sec=timestep_f,
            engine_option=engine_option,
        )
        takeoff_path = to_path
        takeoff_hover = to_hover
        takeoff_ground_roll_ft = ground_roll_ft

        # Run climb simulation from liftoff to failure altitude
        failure_point, failure_hdg, climb_end_time, cl_path, cl_hover = simulate_climb_phase(
            start_point=liftoff_point,
            heading_deg=runway_hdg,
            start_alt_agl=0.0,  # Liftoff at ground level
            target_alt_agl=altitude_agl_f,  # Climb to failure altitude
            ac=ac,
            weight_lbs=weight_lbs_f,
            oat_c=oat_c_f,
            altimeter_inhg=altimeter_inhg_f,
            field_elev_ft=touchdown_elev_f,
            wind_dir=wind_dir_f,
            wind_speed=wind_speed_f,
            timestep_sec=timestep_f,
            engine_option=engine_option,
            start_time=liftoff_time,
        )
        climb_path = cl_path
        climb_hover = cl_hover

        # Set the glide start point to the engine failure position
        glide_start_point = GeoPoint(float(failure_point["lat"]), float(failure_point["lon"]))
        takeoff_climb_time = climb_end_time

        # Override start IAS to use Vy from climb (or best glide if lower)
        vy_kias = ac.get("Vy", 75)
        if start_ias_f <= 0:
            start_ias_f = vy_kias
    else:
        # Legacy mode: start_point is already the engine failure point
        if actual_start_point is not None:
            if isinstance(actual_start_point, dict):
                glide_start_point = GeoPoint(float(actual_start_point["lat"]), float(actual_start_point["lon"]))
            else:
                glide_start_point = actual_start_point

    if glide_start_point is None:
        return [], [], {"success": False, "reason": "no_glide_start_point"}

    def eval_at(alt_agl: float, intercept_bank_deg: float, use_dynamic_start: bool = False):
        """
        Evaluate the impossible turn at a given altitude and bank angle.

        If use_dynamic_start=True and we have takeoff/climb data, calculate where
        the aircraft would actually be at the test altitude (based on climb from runway).
        This is critical for accurate minimum altitude determination.
        """
        eval_start_point = glide_start_point

        # For minimum altitude search with takeoff/climb, calculate the actual failure position
        if use_dynamic_start and include_takeoff_climb and threshold_point and liftoff_point:
            # Run climb simulation to this test altitude to find where failure would occur
            try:
                test_failure_pt, _, _, _, _ = simulate_climb_phase(
                    start_point=liftoff_point,
                    heading_deg=runway_hdg,
                    start_alt_agl=0.0,
                    target_alt_agl=float(alt_agl),
                    ac=ac,
                    weight_lbs=weight_lbs_f,
                    oat_c=oat_c_f,
                    altimeter_inhg=altimeter_inhg_f,
                    field_elev_ft=touchdown_elev_f,
                    wind_dir=wind_dir_f,
                    wind_speed=wind_speed_f,
                    timestep_sec=timestep_f,
                    engine_option=engine_option,
                    start_time=0.0,
                )
                eval_start_point = GeoPoint(float(test_failure_pt["lat"]), float(test_failure_pt["lon"]))
            except Exception:
                # Fall back to original start point if climb simulation fails
                pass

        return _run_impossible_turn_once(
            start_point=eval_start_point,
            runway_heading_deg=runway_hdg,
            turn_dir=turn_dir,
            bank_deg=float(intercept_bank_deg),
            reaction_sec=reaction_f,
            start_ias_kias=start_ias_f,
            altitude_agl=float(alt_agl),
            align_window_deg=align_window_f,
            ac=ac,
            engine_option=engine_option,
            weight_lbs=weight_lbs_f,
            oat_c=oat_c_f,
            altimeter_inhg=altimeter_inhg_f,
            wind_dir=wind_dir_f,
            wind_speed=wind_speed_f,
            timestep_sec=timestep_f,
            flap_config=flap_config,
            prop_config=prop_config,
            touchdown_elev_ft=touchdown_elev_f,
            intercept_angle_deg=float(intercept_angle_deg),
            xtrack_align_gate_ft=float(xtrack_align_gate_ft),
            along_align_gate_ft=float(along_align_gate_ft),
            jink_bank_cap_deg=float(jink_bank_cap_deg),
            jink_hdg_tol_deg=float(jink_hdg_tol_deg),
            jink_xtrack_tol_ft=float(jink_xtrack_tol_ft),
            runway_threshold_point=runway_threshold_geopoint,  # Pass threshold for centerline reference
        )

    def _turn1_time_sec(hover: list) -> float:
        if not hover:
            return 0.0
        dt = timestep_f
        return dt * sum(1 for h in hover if str(h.get("phase", "")).lower() == "turn1")

    def score_failure(meta: dict, hover: list, intercept_bank_deg: float) -> float:
        best_xerr = abs(float(meta.get("best_xtrack_ft", 1e9)))
        total_t = float(meta.get("time_sec", len(hover) * timestep_f))
        return float(
            - (best_xerr * 10.0)
            + (total_t * 1.0)
            - (float(intercept_bank_deg) * 2.0)
        )

    def better_choice(candidate: dict, incumbent: dict) -> bool:
        if incumbent is None:
            return True
        eps = 1e-6
        cs = float(candidate["score"])
        iscore = float(incumbent["score"])
        if cs > iscore + eps:
            return True
        if abs(cs - iscore) <= 0.25:
            return float(candidate["bank"]) < float(incumbent["bank"])
        return False

    def find_best_bank_for_alt(alt_agl: float, use_dynamic_start: bool = False):
        best_fail = None

        b = float(bank_min_deg)
        bmax = float(bank_max_deg)
        bstep = max(0.1, float(bank_step_deg))

        while b <= bmax + 1e-9:
            path, hover, meta = eval_at(alt_agl, b, use_dynamic_start=use_dynamic_start)
            meta = meta if isinstance(meta, dict) else {}

            if meta.get("success", False) and meta.get("captured", False):
                xerr = abs(float(meta.get("final_xtrack_ft", 1e9)))
                herr = abs(float(meta.get("final_hdg_err_deg", 1e9)))

                xtol = float(meta.get("centerline_xtol_ft", 150.0))
                if (xerr <= xtol) and (herr <= float(align_window_f)):
                    return {"bank": b, "path": path, "hover": hover, "meta": meta, "score": 0.0}

            sf = score_failure(meta, hover, b)
            candf = {"bank": b, "path": path, "hover": hover, "meta": meta, "score": sf}
            if better_choice(candf, best_fail):
                best_fail = candf

            b += bstep

        return best_fail

    best_run = find_best_bank_for_alt(altitude_agl_f)
    if not best_run:
        return [], [], {"success": False, "reason": "bank_search_failed"}

    glide_path = best_run["path"]
    glide_hover = best_run["hover"]
    meta = best_run["meta"] if isinstance(best_run["meta"], dict) else {}

    meta["bank_deg"] = float(best_run["bank"])
    meta["jink_bank_cap_deg"] = float(jink_bank_cap_deg)
    meta["flap_config"] = str(flap_config)
    meta["prop_config"] = str(prop_config)

    # === COMBINE PATHS AND HOVER DATA ===
    if include_takeoff_climb and (takeoff_path or climb_path):
        # Adjust glide hover times to continue from takeoff/climb time
        adjusted_glide_hover = []
        for h in glide_hover:
            h_copy = dict(h)
            h_copy["time"] = h_copy.get("time", 0.0) + takeoff_climb_time
            adjusted_glide_hover.append(h_copy)

        # Combine paths (removing duplicate points at boundaries)
        combined_path = []
        if takeoff_path:
            combined_path.extend(takeoff_path)
        if climb_path:
            # Skip first point if it duplicates last takeoff point
            start_idx = 1 if combined_path and climb_path else 0
            combined_path.extend(climb_path[start_idx:])
        if glide_path:
            # Skip first point if it duplicates last climb point
            start_idx = 1 if combined_path and glide_path else 0
            combined_path.extend(glide_path[start_idx:])

        # Combine hover data
        combined_hover = []
        combined_hover.extend(takeoff_hover)
        combined_hover.extend(climb_hover)
        combined_hover.extend(adjusted_glide_hover)

        path = combined_path
        hover = combined_hover

        # Add takeoff/climb metadata
        meta["include_takeoff_climb"] = True
        meta["takeoff_time_sec"] = float(takeoff_hover[-1]["time"]) if takeoff_hover else 0.0
        meta["liftoff_ias_kias"] = float(takeoff_hover[-1].get("ias", 0)) if takeoff_hover else 0.0
        meta["ground_roll_ft"] = float(takeoff_ground_roll_ft) if takeoff_ground_roll_ft else 0.0
        meta["climb_time_sec"] = takeoff_climb_time - (meta["takeoff_time_sec"])
        meta["failure_altitude_agl"] = altitude_agl_f
        if threshold_point:
            meta["threshold_point"] = threshold_point
    else:
        path = glide_path
        hover = glide_hover
        meta["include_takeoff_climb"] = False

    min_feasible = None
    if find_min_alt:
        low = float(min_alt_floor_agl)
        high = float(max_alt_ceiling_agl)
        res = max(1.0, float(min_alt_resolution_ft))

        # Use dynamic start point calculation when takeoff/climb is included
        # This ensures each test altitude uses the correct engine failure position
        use_dynamic = include_takeoff_climb and threshold_point is not None

        hi_run = find_best_bank_for_alt(high, use_dynamic_start=use_dynamic)
        if hi_run and hi_run["meta"].get("success", False):
            lo_run = find_best_bank_for_alt(low, use_dynamic_start=use_dynamic)
            if lo_run and lo_run["meta"].get("success", False):
                min_feasible = low
            else:
                while (high - low) > res:
                    mid = 0.5 * (low + high)
                    mid_run = find_best_bank_for_alt(mid, use_dynamic_start=use_dynamic)
                    if mid_run and mid_run["meta"].get("success", False):
                        high = mid
                    else:
                        low = mid
                min_feasible = high

    meta["min_feasible_alt_agl"] = min_feasible
    return path, hover, meta
