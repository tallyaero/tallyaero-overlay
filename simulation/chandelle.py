"""
Chandelle simulation module.

A chandelle is a maximum performance climbing turn that combines a 180° change
in direction with a climb, beginning from straight-and-level flight and ending
in a wings-level, nose-high attitude at minimum controllable airspeed.

FAA ACS Standards (Commercial Pilot):
- Entry: Straight and level at Va or manufacturer recommended speed
- Bank angle: Approximately 30° (held constant during first 90°)
- First 90°: Constant bank, increasing pitch, climb develops
- Second 90°: Constant pitch, decreasing bank (rollout)
- Completion: Wings level at 180° point, within 10 KIAS of power-on stall speed (Vs)
- Heading tolerance: ±10°
- Minimum altitude: 1,500 ft AGL

Power: FULL POWER applied at entry and maintained throughout.
The maneuver trades airspeed for altitude using maximum available power.
"""
import math
from geopy import Point as GeoPoint

from physics import (
    compute_pressure_altitude,
    compute_true_airspeed,
    compute_air_density,
    point_from,
    G_FPS2,
    FT_PER_NM,
    rho_sl,
)


def _wrap_360(angle: float) -> float:
    """Normalize angle to [0, 360)."""
    return angle % 360.0


def _angle_diff_deg(a: float, b: float) -> float:
    """Compute signed difference (a - b), result in [-180, 180]."""
    diff = (a - b + 540.0) % 360.0 - 180.0
    return diff


def _wind_components_from_dir(wind_from_deg: float, wind_speed_kt: float):
    """
    Convert wind FROM direction and speed to north/east velocity components.
    Returns (wn_fps, we_fps) - wind velocity in ft/s.
    """
    wind_to_rad = math.radians((wind_from_deg + 180.0) % 360.0)
    wind_fps = wind_speed_kt * 1.68781
    wn_fps = wind_fps * math.cos(wind_to_rad)
    we_fps = wind_fps * math.sin(wind_to_rad)
    return wn_fps, we_fps


def _heading_from_track_components(vn: float, ve: float) -> float:
    """Convert north/east velocity components to heading in degrees."""
    return _wrap_360(math.degrees(math.atan2(ve, vn)))


def _interpolate_stall_speed(ac: dict, weight_lb: float, config: str = "clean") -> float:
    """
    Interpolate stall speed from aircraft JSON stall_speeds table.

    Args:
        ac: Aircraft data dict
        weight_lb: Current aircraft weight in pounds
        config: Flap configuration ('clean', 'takeoff', 'landing')

    Returns:
        Stall speed in KIAS for the given weight and configuration
    """
    if not ac:
        return 48.0  # Default fallback

    stall_data = ac.get("stall_speeds", {}).get(config, {})
    weights = stall_data.get("weights", [])
    speeds = stall_data.get("speeds", [])

    if not weights or not speeds or len(weights) != len(speeds):
        # Fallback to single_engine_limits if available
        sel = ac.get("single_engine_limits", {})
        vs = sel.get("vs", sel.get("vs0", 48.0))
        return float(vs) if vs else 48.0

    # Interpolate
    if weight_lb <= weights[0]:
        return float(speeds[0])
    if weight_lb >= weights[-1]:
        return float(speeds[-1])

    # Linear interpolation
    for i in range(len(weights) - 1):
        if weights[i] <= weight_lb <= weights[i + 1]:
            ratio = (weight_lb - weights[i]) / (weights[i + 1] - weights[i])
            vs = speeds[i] + ratio * (speeds[i + 1] - speeds[i])
            return float(vs)

    return float(speeds[-1])


def _get_engine_horsepower(ac: dict, altitude_ft: float, engine_option: str = None) -> float:
    """
    Get TOTAL available engine horsepower at altitude (sum across all
    installed engines).

    Pre-fix this returned per-engine HP regardless of `engine_count` and
    always picked the first engine option. Now honors the caller's
    `engine_option` choice (multi-variant aircraft) and multiplies the
    per-engine HP by `engine_count` for twins.

    Args:
        ac: Aircraft data dict
        altitude_ft: Altitude in feet (used for DA derate)
        engine_option: Name of engine in `engine_options` to use; defaults
                       to first entry when omitted.
    """
    if not ac:
        return 180.0  # Default fallback

    engine_options = ac.get("engine_options", {})
    if not engine_options:
        return 180.0

    if engine_option and engine_option in engine_options:
        engine_name = engine_option
    else:
        engine_name = list(engine_options.keys())[0]
    engine_data = engine_options[engine_name]

    # Get power curve
    power_curve = engine_data.get("power_curve", {})
    sea_level_max = power_curve.get("sea_level_max", engine_data.get("horsepower", 180))
    derate_per_1000ft = power_curve.get("derate_per_1000ft", 0.03)

    # Derate for altitude (typically 3% per 1000 ft)
    altitude_factor = 1.0 - (altitude_ft / 1000.0) * derate_per_1000ft
    altitude_factor = max(0.5, altitude_factor)  # Don't go below 50%

    # Total installed HP — twins use both engines for this maneuver.
    n_engines = int(ac.get("engine_count", 1) or 1)
    return float(sea_level_max) * altitude_factor * n_engines


def _compute_climb_rate(
    hp_available: float,
    weight_lb: float,
    tas_knots: float,
    bank_deg: float,
    ac: dict = None,
    altitude_ft: float = 3000.0,
    oat_c: float = 15.0,
    altimeter_inhg: float = 29.92,
) -> float:
    """
    Compute climb rate based on excess power.

    Uses: Rate of Climb = (Excess HP × 33000) / Weight
    Where: Excess HP = HP_available - HP_required

    HP_required is estimated from drag at current speed.
    Bank angle reduces effective climb due to increased load factor.

    Density is now computed from the aircraft's actual altitude + OAT
    (pre-fix used `rho_sl * 0.9` for every alt — a 3000-ft proxy that
    over-estimated drag at high alt and under-estimated near SL).
    """
    if weight_lb <= 0 or tas_knots <= 0:
        return 0.0

    # Get aircraft drag characteristics if available
    if ac:
        cd0 = ac.get("CD0", 0.027)
        wing_area = ac.get("wing_area", 174.0)
        aspect_ratio = ac.get("aspect_ratio", 7.3)
        e = ac.get("e", 0.81)
    else:
        cd0 = 0.027
        wing_area = 174.0
        aspect_ratio = 7.3
        e = 0.81

    tas_fps = tas_knots * 1.68781

    # Density at current altitude (ISA + altimeter setting + OAT).
    try:
        palt = compute_pressure_altitude(altitude_ft, altimeter_inhg)
        rho = compute_air_density(palt, oat_c)
    except Exception:
        rho = rho_sl * 0.9  # legacy fallback
    q = 0.5 * rho * tas_fps**2

    # Lift coefficient required for level flight
    # In a bank, we need more lift: L = W / cos(bank)
    load_factor = 1.0 / math.cos(math.radians(abs(bank_deg))) if abs(bank_deg) < 89 else 10.0
    weight_apparent = weight_lb * load_factor

    cl = weight_apparent / (q * wing_area) if q * wing_area > 0 else 0.5
    cl = min(cl, 1.5)  # Cap at reasonable CL

    # Induced drag coefficient
    cd_induced = cl**2 / (math.pi * aspect_ratio * e)

    # Total drag coefficient
    cd_total = cd0 + cd_induced

    # Drag force
    drag_lb = q * wing_area * cd_total

    # Power required (hp) = Drag × Velocity / 550
    hp_required = (drag_lb * tas_fps) / 550.0

    # Excess power
    hp_excess = hp_available - hp_required
    hp_excess = max(0, hp_excess)  # Can't have negative excess in a climb

    # Rate of climb (fpm) = (Excess HP × 33000) / Weight
    roc_fpm = (hp_excess * 33000.0) / weight_lb

    # Apply load factor penalty (climbing in a turn is less efficient)
    roc_fpm = roc_fpm / load_factor

    return max(0.0, roc_fpm)


def simulate_chandelle(
    entry_point: dict,
    entry_heading_deg: float,
    turn_direction: str,
    entry_altitude_ft: float,
    entry_ias_knots: float,
    bank_angle_deg: float = 30.0,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    oat_c: float = 15.0,
    altimeter_inhg: float = 29.92,
    field_elev_ft: float = 0.0,
    ac: dict = None,
    weight_lb: float = None,
    timestep_sec: float = 0.5,
    power_setting: float = 1.0,
    wind_profile=None,
    engine_option: str = None,
) -> tuple:
    """
    Simulate a chandelle maneuver with proper wind effects and aircraft data.

    The chandelle is divided into two phases:
    - First 90° (0-90°): Constant bank (~30°), increasing pitch, climb develops
    - Second 90° (90-180°): Constant pitch attitude, decreasing bank to wings level

    POWER: Full throttle applied at entry and maintained throughout.
    EXIT: Within 10 KIAS of power-on stall speed (Vs), wings level, 180° heading change.

    Args:
        entry_point: Dict with 'lat' and 'lon' keys
        entry_heading_deg: Entry heading in degrees (true)
        turn_direction: 'left' or 'right'
        entry_altitude_ft: Entry altitude in feet AGL
        entry_ias_knots: Entry indicated airspeed in knots (typically Va)
        bank_angle_deg: Maximum bank angle (default 30° per ACS)
        wind_dir_deg: Wind direction (FROM) in degrees
        wind_speed_kt: Wind speed in knots
        oat_c: Outside air temperature in Celsius
        altimeter_inhg: Altimeter setting in inches Hg
        field_elev_ft: Field elevation in feet MSL
        ac: Aircraft data dict (for stall speeds, engine data)
        weight_lb: Aircraft weight in pounds (for stall speed interpolation)
        timestep_sec: Time step in seconds

    Returns:
        Tuple of (path, hover_data) where:
            - path: List of [lat, lon] coordinate pairs
            - hover_data: List of dicts containing flight telemetry
    """
    if entry_point is None:
        return [], []

    dt = float(timestep_sec) if timestep_sec and timestep_sec > 0 else 0.5

    # Parse and validate inputs
    entry_altitude_ft = float(entry_altitude_ft or 3000.0)
    entry_ias_knots = float(entry_ias_knots or 100.0)
    bank_angle_deg = float(bank_angle_deg or 30.0)
    entry_heading_deg = _wrap_360(float(entry_heading_deg or 0.0))
    wind_dir_deg = float(wind_dir_deg or 0.0)

    wind_speed_kt = float(wind_speed_kt or 0.0)
    oat_c = float(oat_c if oat_c is not None else 15.0)
    altimeter_inhg = float(altimeter_inhg if altimeter_inhg is not None else 29.92)
    field_elev_ft = float(field_elev_ft or 0.0)

    # Wind handling: user surface wind is authoritative. When a column is
    # provided we override its SFC layer with the user value and then
    # sample per-tick by altitude inside the loop. (Pre-fix this branch
    # silently overwrote wind_dir_deg/wind_speed_kt with the column's
    # mid-altitude wind — user edits ignored.)
    if wind_profile is not None:
        try:
            wind_profile = wind_profile.with_surface_override(
                wind_dir_deg, wind_speed_kt,
                surface_alt_ft_msl=field_elev_ft,
            )
        except Exception:
            pass

    # POH dynamics — roll_rate_dps drives the chandelle entry roll-in
    # rate. Pre-fix this was a single hardcoded 10 dps for every
    # airframe; some aircraft have POH-cited rates 5-10x higher.
    try:
        from core.dynamics import dynamics_for
        pd_dyn = dynamics_for(ac) if ac is not None else {}
    except Exception:
        pd_dyn = {}
    poh_roll_rate_dps = float(pd_dyn.get("roll_rate_dps", 10.0))

    # Turn direction: left = -1, right = +1
    turn_sign = -1.0 if str(turn_direction).lower().startswith('l') else 1.0

    # Target heading is 180° from entry (will be re-pinned after power-truncation
    # below if power_setting < 0.5).
    target_heading = _wrap_360(entry_heading_deg + 180.0)

    # Compute initial TAS
    alt_msl_ft = field_elev_ft + entry_altitude_ft
    pressure_alt_ft = compute_pressure_altitude(alt_msl_ft, altimeter_inhg)
    entry_tas_knots = compute_true_airspeed(entry_ias_knots, pressure_alt_ft, oat_c)
    entry_tas_knots = float(entry_tas_knots) if entry_tas_knots and entry_tas_knots > 1 else entry_ias_knots

    # Get aircraft weight - use provided or get from aircraft data
    if weight_lb is None and ac:
        # Try to get reference weight from aircraft
        weight_lb = ac.get("max_takeoff_weight", ac.get("gross_weight", 2300.0))
    elif weight_lb is None:
        weight_lb = 2300.0  # Default GA aircraft weight
    weight_lb = float(weight_lb)

    # Get stall speed using proper weight interpolation
    # For chandelle, we use "clean" configuration (no flaps)
    vs_clean = _interpolate_stall_speed(ac, weight_lb, "clean")

    # Power-on stall speed is typically 5-7% lower than power-off
    # due to propwash over the wing and reduced angle of attack required
    vs_power_on = vs_clean * 0.93

    # Target exit speed: within 10 KIAS of power-on stall speed
    # Aim for 1.05 * Vs_power_on (just slightly above stall)
    target_exit_ias = vs_power_on * 1.05

    # Get full throttle horsepower at entry altitude. Honors engine_option
    # + multi-engine total power.
    hp_available = _get_engine_horsepower(ac, entry_altitude_ft, engine_option)

    # Design Directive — Chandelle is a FULL-POWER maneuver (design = 1.0).
    # Scale HP by power_setting. Below 50% the airplane cannot complete the
    # 180° heading change at target IAS — we truncate the path proportionally
    # and surface failure_reason on the last hover point.
    try:
        power_pct = float(power_setting) if power_setting is not None else 1.0
    except (TypeError, ValueError):
        power_pct = 1.0
    power_pct = max(0.0, min(1.0, power_pct))
    design_power = 1.0
    hp_available *= power_pct
    # Max heading change the airplane will be allowed to reach.
    if power_pct < 0.5:
        # Linear truncation: 0% → 0°, 50% → 180°. Clamp to a minimum of 30°
        # so the rendered path is at least visible on the map.
        max_progress_deg = max(30.0, 180.0 * (power_pct / 0.5))
    else:
        max_progress_deg = 180.0

    # Re-pin target_heading to the truncated end-heading so the rollout snap
    # lands where the airplane actually quit (not 180° away).
    target_heading = _wrap_360(entry_heading_deg + turn_sign * max_progress_deg)

    # Wind components — recomputed per-tick when wind_profile present
    # (per-altitude lookup); constant otherwise.
    def _resolve_wind_at(alt_msl_now: float):
        if wind_profile is None:
            return _wind_components_from_dir(wind_dir_deg, wind_speed_kt)
        try:
            wd, ws = wind_profile.at(alt_msl_now)
            return _wind_components_from_dir(float(wd), float(ws))
        except Exception:
            return _wind_components_from_dir(wind_dir_deg, wind_speed_kt)

    wn_fps, we_fps = _resolve_wind_at(field_elev_ft + entry_altitude_ft)

    # Initialize state
    cur = GeoPoint(entry_point["lat"], entry_point["lon"])
    hdg = entry_heading_deg
    alt_agl = entry_altitude_ft
    ias = entry_ias_knots
    t = 0.0

    path = []
    hover = []

    # Chandelle parameters
    max_bank = abs(bank_angle_deg)
    total_turn = 180.0  # Total heading change

    # Pitch parameters - start at level, increase to max during first 90°
    # Max pitch around 12-15° for typical GA aircraft
    max_pitch_deg = 15.0

    def compute_tas_from_ias(ias_kt, alt_ft):
        """Compute TAS from IAS at current altitude."""
        alt_msl = field_elev_ft + alt_ft
        palt = compute_pressure_altitude(alt_msl, altimeter_inhg)
        tas = compute_true_airspeed(ias_kt, palt, oat_c)
        return float(tas) if tas and tas > 1 else ias_kt

    def compute_motion(tas_kt):
        """Compute ground velocity components and track from current heading."""
        tas_fps = tas_kt * 1.68781
        hdg_rad = math.radians(hdg)
        va_n = tas_fps * math.cos(hdg_rad)
        va_e = tas_fps * math.sin(hdg_rad)
        vg_n = va_n + wn_fps
        vg_e = va_e + we_fps
        gs_fps = math.hypot(vg_n, vg_e)
        gs_kt = gs_fps / 1.68781
        track_deg = _heading_from_track_components(vg_n, vg_e)
        drift_deg = _angle_diff_deg(track_deg, hdg)
        return gs_fps, gs_kt, track_deg, drift_deg

    def record(gs_kt, aob_deg, vs_fpm, track_deg, drift_deg, pitch_deg, segment, current_hp=None):
        """Record a point in path and hover data."""
        load_factor = 1.0 / math.cos(math.radians(aob_deg)) if abs(aob_deg) < 89.9 else None
        hover.append({
            "time": round(t, 2),
            "alt": round(alt_agl, 1),
            "tas": round(tas, 1),
            "ias": round(ias, 1),
            "gs": round(gs_kt, 1),
            "aob": round(aob_deg, 1),
            # Heading progress so far through the maneuver (degrees from
            # entry). Used by the callback to mark "90°" / "Exit" on the
            # time scrubber. Pre-fix the slider tried to read this field
            # but it was never emitted.
            "turn_progress": round(accumulated_turn, 1),
            "load_factor": round(load_factor, 2) if load_factor is not None else None,
            "vs": round(vs_fpm, 0),
            "track": round(track_deg, 1),
            "heading": round(hdg, 1),
            "drift": round(drift_deg, 1) if drift_deg is not None else 0.0,
            "pitch": round(pitch_deg, 1),
            "segment": segment,
            # Additional chandelle-specific data
            "vs_ref": round(vs_power_on, 1),  # Power-on stall reference
            "speed_margin": round(ias - vs_power_on, 1),  # Margin above stall
            "hp": round(current_hp, 0) if current_hp else round(hp_available, 0),
            "power": "FULL",  # Full power throughout chandelle
        })
        path.append([cur.latitude, cur.longitude])

    # Calculate how much heading change per phase
    first_phase_turn = 90.0  # First 90°
    second_phase_turn = 90.0  # Second 90°

    accumulated_turn = 0.0
    bank = 0.0
    pitch = 0.0

    # Roll rate — POH-cited (or class-derived) per airframe, not the
    # blanket 10 dps the chandelle used to assume.
    roll_rate = poh_roll_rate_dps

    # Phase tracking
    phase = "roll_in"  # roll_in -> first_90 -> second_90 -> done

    while phase != "done":
        # Compute current TAS
        tas = compute_tas_from_ias(ias, alt_agl)
        tas_fps = tas * 1.68781

        # Power-truncation kill switch: if off-design power has held us back
        # past the allowed heading change, force rollout regardless of phase.
        if phase not in ("rollout", "done") and accumulated_turn >= max_progress_deg - 0.5:
            phase = "rollout"

        # Phase logic
        if phase == "roll_in":
            # Roll into the bank
            bank = min(bank + roll_rate * dt, max_bank)
            # Start increasing pitch
            pitch = min(pitch + (max_pitch_deg / (max_bank / roll_rate)) * dt, max_pitch_deg * 0.3)
            segment = "roll_in"
            if bank >= max_bank - 0.1:
                bank = max_bank
                phase = "first_90"

        elif phase == "first_90":
            # Constant bank, increasing pitch
            bank = max_bank
            # Linearly increase pitch to max over the first 90° of turn
            turn_progress = accumulated_turn / first_phase_turn
            pitch = max_pitch_deg * min(1.0, turn_progress * 1.2)  # Reach max pitch before 90°
            segment = "first_90"

            # Check if we've completed first 90°
            if accumulated_turn >= first_phase_turn:
                phase = "second_90"

        elif phase == "second_90":
            # Constant pitch, decreasing bank
            pitch = max_pitch_deg  # Hold constant pitch

            # Linear bank reduction over second 90°
            # Bank goes from max_bank to 0 as we turn from 90° to 180°
            turn_into_second = accumulated_turn - first_phase_turn
            rollout_progress = min(1.0, turn_into_second / second_phase_turn)
            bank = max_bank * (1.0 - rollout_progress)
            bank = max(0.0, bank)
            segment = "second_90"

            # Check if we've completed the turn (bank near zero or accumulated turn reached)
            if bank < 0.5 or accumulated_turn >= total_turn - 1.0:
                phase = "rollout"

        elif phase == "rollout":
            # Final correction to exact heading
            hdg = target_heading
            bank = 0.0
            segment = "rollout"

            # Record final point
            gs_fps, gs_kt, track_deg, drift_deg = compute_motion(tas)
            vs_fpm = 0.0  # Level off
            final_hp = _get_engine_horsepower(ac, alt_agl)
            record(gs_kt, 0.0, vs_fpm, track_deg, drift_deg, pitch, segment, final_hp)

            # Move one more step
            step_ft = gs_fps * dt
            step_nm = step_ft / FT_PER_NM
            cur = point_from(cur, track_deg, step_nm)
            t += dt

            phase = "done"
            continue

        # Compute turn rate from bank and TAS
        if bank > 0.1:
            bank_rad = math.radians(bank)
            turn_rate_rps = (G_FPS2 * math.tan(bank_rad)) / max(1.0, tas_fps)
            turn_rate_dps = math.degrees(turn_rate_rps)
        else:
            turn_rate_dps = 0.0

        # Update heading
        dpsi = turn_rate_dps * dt
        hdg = _wrap_360(hdg + turn_sign * dpsi)
        accumulated_turn += dpsi

        # Per-tick wind sampling — picks up boundary-layer shear when a
        # wind_profile is provided.
        wn_fps, we_fps = _resolve_wind_at(field_elev_ft + alt_agl)

        # Compute climb rate using physics-based model.
        # Full power scaled by power_setting; HP derates by altitude.
        # Density now reflects current altitude + OAT (not a flat 3000-ft
        # proxy as in the pre-fix code).
        current_hp = _get_engine_horsepower(ac, alt_agl, engine_option)
        current_hp *= power_pct

        base_climb_fpm = _compute_climb_rate(
            current_hp, weight_lb, tas, bank, ac,
            altitude_ft=alt_agl, oat_c=oat_c, altimeter_inhg=altimeter_inhg,
        )

        # Scale climb by pitch angle (0 pitch = level flight, max pitch = max climb)
        pitch_factor = pitch / max_pitch_deg if max_pitch_deg > 0 else 0.0
        pitch_factor = max(0.0, min(1.0, pitch_factor))

        vs_fpm = base_climb_fpm * pitch_factor

        # As we approach stall speed, climb rate diminishes
        # Energy must be conserved - less speed margin means less climb available
        speed_margin = (ias - target_exit_ias) / max(1.0, entry_ias_knots - target_exit_ias)
        speed_margin = max(0.0, min(1.0, speed_margin))
        vs_fpm = vs_fpm * (0.3 + 0.7 * speed_margin)  # Never fully zero climb

        # Power-setting penalty is now applied UPSTREAM via
        # `current_hp *= power_pct` (which makes the excess-power math
        # honest about how much energy the engine is actually delivering).
        # The earlier extra `vs_fpm *= power_pct` here was double-scaling.

        vs_fpm = max(0.0, vs_fpm)  # No descent during chandelle

        # Update altitude
        alt_agl += (vs_fpm / 60.0) * dt

        # Update airspeed using energy conservation
        # Total energy = kinetic + potential: E = 0.5*m*V^2 + m*g*h
        # With full power, we're adding energy, but trading speed for altitude
        #
        # Energy method: dV/dt = g * (T-D)/W - g*sin(gamma)
        # Where gamma is flight path angle, T is thrust, D is drag
        #
        # Simplified: speed loss proportional to climb rate and pitch
        # Higher pitch = more energy going to altitude = faster speed decay
        #
        # Target: reach target_exit_ias at the end of the maneuver
        # We need to lose (entry_ias - target_exit_ias) over ~180° of turn

        # Calculate expected deceleration to hit target at end
        # Typical chandelle takes 20-35 seconds depending on bank and speed
        total_ias_change = entry_ias_knots - target_exit_ias
        expected_duration = 25.0  # Approximate duration in seconds

        # Base deceleration rate
        base_decel_rate = total_ias_change / expected_duration  # knots per second

        # Scale by pitch (higher pitch = faster energy trade)
        pitch_decel_factor = 0.5 + 0.5 * (pitch / max_pitch_deg)

        # Scale by climb rate (more climb = more speed loss)
        climb_decel_factor = 0.8 + 0.2 * (vs_fpm / max(1.0, base_climb_fpm))

        ias_loss = base_decel_rate * pitch_decel_factor * climb_decel_factor * dt
        ias = max(target_exit_ias, ias - ias_loss)

        # Compute motion
        gs_fps, gs_kt, track_deg, drift_deg = compute_motion(tas)

        # Record point with current engine power (apply turn_sign to bank for L/R display)
        record(gs_kt, turn_sign * bank, vs_fpm, track_deg, drift_deg, pitch, segment, current_hp)

        # Move position
        step_ft = gs_fps * dt
        step_nm = step_ft / FT_PER_NM
        cur = point_from(cur, track_deg, step_nm)

        # Advance time
        t += dt

        # Safety limit
        if t > 120:  # 2 minutes max for a chandelle
            break

    # Surface power / off-design metadata on the last hover point so the
    # callback can render a verdict without recomputing.
    if hover:
        last = hover[-1]
        last["power_setting"] = round(power_pct, 3)
        last["design_power"] = design_power
        last["max_progress_deg"] = round(max_progress_deg, 1)
        last["altitude_gain_ft"] = round(alt_agl - entry_altitude_ft, 1)
        # Surface the correct Vs + load-factor-adjusted stall speed so the
        # callback no longer needs to read the broken
        # `stall_speed_clean_kias` key. Power-on Vs is ~7% below power-off.
        load_factor_at_max_bank = (1.0 / math.cos(math.radians(abs(bank_angle_deg)))
                                   if abs(bank_angle_deg) < 89.9 else float("inf"))
        vs_at_max_bank = (vs_power_on * math.sqrt(load_factor_at_max_bank)
                           if math.isfinite(load_factor_at_max_bank) else None)
        # min IAS during the maneuver — the worst-case approach to stall.
        min_ias_through_run = min(p.get("ias", float("inf")) for p in hover) if hover else None
        # Two margins worth reporting separately:
        #   - max-bank margin: how close min-IAS came to Vs×√n at 30°
        #     (the "in-turn" stall threat the pilot is fighting)
        #   - exit margin: how close min-IAS is to wings-level power-on Vs
        #     (the ACS-graded exit condition)
        exit_margin = (
            round(min_ias_through_run - vs_power_on, 1)
            if (min_ias_through_run is not None and vs_power_on)
            else None
        )
        max_bank_margin = (
            round(min_ias_through_run - vs_at_max_bank, 1)
            if (min_ias_through_run is not None and vs_at_max_bank)
            else None
        )
        last["vs_clean_kt"] = round(vs_clean, 1)
        last["vs_power_on_kt"] = round(vs_power_on, 1)
        last["vs_at_bank_kt"] = round(vs_at_max_bank, 1) if vs_at_max_bank else None
        last["min_ias_kt"] = round(min_ias_through_run, 1) if min_ias_through_run is not None else None
        last["stall_margin_kt"] = exit_margin  # ACS-graded exit margin
        last["stall_margin_in_turn_kt"] = max_bank_margin
        last["roll_rate_dps_used"] = round(roll_rate, 1)
        last["wind_profile_used"] = wind_profile is not None
        last["engine_option"] = engine_option
        if power_pct < 0.5:
            last["failure_reason"] = (
                f"Insufficient power to complete 180° — reached "
                f"{accumulated_turn:.0f}° at {power_pct*100:.0f}% power"
            )

    return path, hover
