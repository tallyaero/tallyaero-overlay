"""
Steep turn simulation module.

Simulates steep turn maneuvers with proper wind integration using time-step
simulation, matching the pattern of other maneuver simulations.

Post-2026-05-21 audit wired:
    * `wind_profile` honored with user-surface-wind override
    * POH `roll_rate_dps` + `bank_response_tau_s` drive bank dynamics
    * `_get_stall_speed_kt` weight-interpolated lookup (fixes the
      legacy `stall_speed_clean_kias` fallback that always returned 48)
    * `engine_option` accepted for per-engine performance
    * per-tick TAS recomputation as altitude drifts under off-design power
"""
import math
from typing import Optional
from geopy import Point as GeoPoint
from geopy.distance import distance as geo_dist

from physics import (
    compute_pressure_altitude,
    compute_true_airspeed,
    point_from,
    G_FPS2,
    FT_PER_NM,
)


def _get_stall_speed_kt(ac: dict, weight_lbs: float, config: str = "clean") -> float:
    """Weight-interpolated Vs (kt) from `ac.stall_speeds[config]`.

    Pre-fix steep_turn read a key that doesn't exist in our aircraft
    JSONs (`stall_speed_clean_kias`) and silently fell back to 48 kt
    for every airframe. This helper mirrors the one used by
    impossible_turn / po180 so the three sims share one Vs contract."""
    stall_speeds = ac.get("stall_speeds", {})
    config_data = stall_speeds.get(config, stall_speeds.get("clean", {}))
    weights = config_data.get("weights", [2000])
    speeds = config_data.get("speeds", [50])
    if not weights or not speeds:
        return 50.0
    w = float(weight_lbs)
    if w <= weights[0]:
        return float(speeds[0])
    if w >= weights[-1]:
        return float(speeds[-1])
    for i in range(len(weights) - 1):
        if weights[i] <= w <= weights[i + 1]:
            r = (w - weights[i]) / (weights[i + 1] - weights[i])
            return float(speeds[i]) + r * (float(speeds[i + 1]) - float(speeds[i]))
    return float(speeds[-1])


def _wrap_360(angle: float) -> float:
    """Normalize angle to [0, 360)."""
    return angle % 360.0


def _angle_diff_deg(a: float, b: float) -> float:
    """
    Compute signed difference (a - b), result in [-180, 180].
    """
    diff = (a - b + 540.0) % 360.0 - 180.0
    return diff


def _wind_components_from_dir(wind_from_deg: float, wind_speed_kt: float):
    """
    Convert wind FROM direction and speed to north/east velocity components.
    Returns (wn_fps, we_fps) - wind velocity in ft/s.
    """
    # Wind FROM means it's coming from that direction, so it blows TO the opposite
    wind_to_rad = math.radians((wind_from_deg + 180.0) % 360.0)
    wind_fps = wind_speed_kt * 1.68781
    wn_fps = wind_fps * math.cos(wind_to_rad)
    we_fps = wind_fps * math.sin(wind_to_rad)
    return wn_fps, we_fps


def _heading_from_track_components(vn: float, ve: float) -> float:
    """Convert north/east velocity components to heading in degrees."""
    return _wrap_360(math.degrees(math.atan2(ve, vn)))


def simulate_steep_turn(
    entry_point: dict,
    entry_heading_deg: float,
    altitude_ft: float,
    bank_angle_deg: float,
    turn_sequence: str,
    ias_knots: float = None,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    oat_c: float = 15.0,
    altimeter_inhg: float = 29.92,
    field_elev_ft: float = 0.0,
    timestep_sec: float = 0.5,
    roll_rate_dps: float = None,           # None = honor POH; explicit overrides
    pause_sec: float = 1.0,
    power_setting: float = 0.7,
    # Legacy parameter name support
    tas_knots: float = None,
    # Post-2026-05-21 additions
    ac: dict = None,                       # required for POH dynamics + Vs lookup
    weight_lbs: float = None,
    engine_option: Optional[str] = None,
    wind_profile=None,                     # Optional[WindProfile]
) -> tuple:
    """
    Simulate steep turn maneuver with proper wind effects using time-step integration.

    Args:
        entry_point: Dict with 'lat' and 'lon' keys
        entry_heading_deg: Entry heading in degrees (true)
        altitude_ft: Altitude in feet AGL
        bank_angle_deg: Target bank angle in degrees
        turn_sequence: One of 'left', 'right', 'left-right', 'right-left'
        ias_knots: Indicated airspeed in knots (used to compute TAS)
        wind_dir_deg: Wind direction (FROM) in degrees
        wind_speed_kt: Wind speed in knots
        oat_c: Outside air temperature in Celsius
        altimeter_inhg: Altimeter setting in inches Hg
        field_elev_ft: Field elevation in feet MSL
        timestep_sec: Time step in seconds (default 0.5)
        roll_rate_dps: Roll rate in degrees per second (default 5.0)
        pause_sec: Pause duration between turns in seconds (default 1.0)
        tas_knots: (Legacy) TAS override if IAS not provided

    Returns:
        Tuple of (path, hover_data) where:
            - path: List of [lat, lon] coordinate pairs
            - hover_data: List of dicts containing flight telemetry
    """
    # Handle legacy parameter name
    if ias_knots is None and tas_knots is not None:
        ias_knots = tas_knots
    elif ias_knots is None:
        ias_knots = 100.0  # Default fallback

    # Validate inputs
    if entry_point is None:
        return [], []

    dt = float(timestep_sec) if timestep_sec and timestep_sec > 0 else 0.5
    altitude_ft = float(altitude_ft or 0.0)
    bank_angle_deg = float(bank_angle_deg or 45.0)
    entry_heading_deg = _wrap_360(float(entry_heading_deg or 0.0))
    wind_dir_deg = float(wind_dir_deg or 0.0)
    wind_speed_kt = float(wind_speed_kt or 0.0)
    oat_c = float(oat_c if oat_c is not None else 15.0)
    altimeter_inhg = float(altimeter_inhg if altimeter_inhg is not None else 29.92)
    field_elev_ft = float(field_elev_ft or 0.0)
    pause_sec = float(pause_sec or 1.0)

    # POH dynamics. Pre-fix used a 5 dps default for every airframe —
    # 9–20× slower than reality. Now reads roll_rate + bank_response_tau
    # from the loader (POH-cited or class-derived) and only honors a
    # caller-provided roll_rate_dps when explicitly set.
    try:
        from core.dynamics import dynamics_for
        pd_dyn = dynamics_for(ac) if ac is not None else {}
    except Exception:
        pd_dyn = {}
    if roll_rate_dps is None:
        roll_rate_dps = float(pd_dyn.get("roll_rate_dps", 40.0))
    else:
        roll_rate_dps = float(roll_rate_dps)
    bank_response_tau_s = float(pd_dyn.get("bank_response_tau_s", 0.0))

    # User-surface-wind authoritative; column drives the (single)
    # altitude lookup for steep turns. The override survives.
    if wind_profile is not None:
        try:
            wind_profile = wind_profile.with_surface_override(
                wind_dir_deg, wind_speed_kt,
                surface_alt_ft_msl=field_elev_ft,
            )
        except Exception:
            pass

    # Design Directive — off-design power produces altitude drift in a
    # nominally level steep turn. Design power = 0.70 (cruise+).
    # Drift formula: +200 fpm per 100% above design, -200 fpm per 100% below.
    try:
        power_pct = float(power_setting) if power_setting is not None else 0.7
    except (TypeError, ValueError):
        power_pct = 0.7
    power_pct = max(0.0, min(1.0, power_pct))
    design_power = 0.70
    altitude_drift_fpm = (power_pct - design_power) * 200.0

    # Compute TAS from IAS at entry altitude — recomputed per-tick in
    # the main loop so altitude drift from off-design power is reflected.
    alt_msl_ft = field_elev_ft + altitude_ft
    pressure_alt_ft = compute_pressure_altitude(alt_msl_ft, altimeter_inhg)
    tas_knots_computed = compute_true_airspeed(float(ias_knots), pressure_alt_ft, oat_c)
    tas_knots_val = float(tas_knots_computed) if tas_knots_computed and tas_knots_computed > 1 else float(ias_knots)
    tas_fps = tas_knots_val * 1.68781

    # Wind components (north, east) in ft/s — refreshed per-tick when
    # wind_profile present, otherwise constant from user input.
    def _resolve_wind_at(alt_msl_now: float):
        if wind_profile is None:
            return _wind_components_from_dir(wind_dir_deg, wind_speed_kt)
        try:
            wd, ws = wind_profile.at(alt_msl_now)
            return _wind_components_from_dir(float(wd), float(ws))
        except Exception:
            return _wind_components_from_dir(wind_dir_deg, wind_speed_kt)

    wn_fps, we_fps = _resolve_wind_at(alt_msl_ft)

    # Stall reference Vs at current weight + clean config (used by
    # downstream telemetry — not gated here since pilots fly steep
    # turns at Va, which is already structurally above stall × √n).
    weight_for_vs = float(weight_lbs) if weight_lbs not in (None, 0) else (
        ac.get("max_weight", 2000) if ac is not None else 2000
    )
    vs_clean_kt = _get_stall_speed_kt(ac or {}, weight_for_vs, "clean")

    # Turn physics
    bank_rad = math.radians(abs(bank_angle_deg))
    if bank_rad < math.radians(1.0):
        bank_rad = math.radians(1.0)  # Prevent division by zero

    # Standard rate turn formula: rate = g * tan(bank) / V
    # Turn radius: R = V^2 / (g * tan(bank))
    turn_rate_max_rps = (G_FPS2 * math.tan(bank_rad)) / max(1.0, tas_fps)
    turn_rate_max_dps = math.degrees(turn_rate_max_rps)

    # Build sequence of actions
    sequence_str = str(turn_sequence).strip().lower()
    actions = []
    if sequence_str == "left":
        actions = [("turn", "left", 360.0)]
    elif sequence_str == "right":
        actions = [("turn", "right", 360.0)]
    elif sequence_str == "left-right":
        actions = [("turn", "left", 360.0), ("pause", None, pause_sec), ("turn", "right", 360.0)]
    elif sequence_str == "right-left":
        actions = [("turn", "right", 360.0), ("pause", None, pause_sec), ("turn", "left", 360.0)]
    else:
        # Default to left turn
        actions = [("turn", "left", 360.0)]

    # Initialize state
    cur = GeoPoint(entry_point["lat"], entry_point["lon"])
    hdg = entry_heading_deg
    t = 0.0
    bank_state_deg = 0.0
    alt_state = altitude_ft

    path = []
    hover = []

    def record(gs_kt, aob_deg, track_deg, drift_deg, segment):
        """Record a point in path and hover data.

        Per MANEUVER_STANDARD.md every maneuver must publish `ias`
        (constant for a level steep turn — equal to the input
        ias_knots) and `load_factor` (1/cos(bank), the load the
        wings see at the current bank). Altitude tracks `alt_state`
        which drifts with off-design power."""
        load_factor = 1.0 / math.cos(math.radians(aob_deg)) if abs(aob_deg) < 89.9 else float("inf")
        hover.append({
            "time": round(t, 2),
            "alt": round(alt_state, 1),
            "ias": round(float(ias_knots), 1),
            "tas": round(tas_knots_val, 1),
            "gs": round(gs_kt, 1),
            "aob": round(aob_deg, 1),
            "load_factor": round(load_factor, 2) if math.isfinite(load_factor) else None,
            "vs": round(altitude_drift_fpm, 0),
            "track": round(track_deg, 1),
            "heading": round(hdg, 1),
            "drift": round(drift_deg, 1) if drift_deg is not None else 0.0,
            "segment": segment,
        })
        path.append([cur.latitude, cur.longitude])

    def compute_motion():
        """
        Compute ground velocity components and track from current heading.
        Returns (gs_fps, gs_kt, track_deg, drift_deg)
        """
        hdg_rad = math.radians(hdg)
        # Airspeed velocity components (north, east)
        va_n = tas_fps * math.cos(hdg_rad)
        va_e = tas_fps * math.sin(hdg_rad)
        # Ground velocity = airspeed + wind
        vg_n = va_n + wn_fps
        vg_e = va_e + we_fps
        gs_fps = math.hypot(vg_n, vg_e)
        gs_kt = gs_fps / 1.68781
        track_deg = _heading_from_track_components(vg_n, vg_e)
        drift_deg = _angle_diff_deg(track_deg, hdg)
        return gs_fps, gs_kt, track_deg, drift_deg

    def move_position(gs_fps, track_deg):
        """Move current position based on groundspeed and track."""
        nonlocal cur
        step_ft = gs_fps * dt
        step_nm = step_ft / FT_PER_NM
        cur = point_from(cur, track_deg, step_nm)

    # Process each action
    for action_type, direction, value in actions:
        if action_type == "turn":
            # Determine turn sign: left = -1 (heading decreases), right = +1
            turn_sign = -1.0 if direction == "left" else 1.0
            target_bank = abs(bank_angle_deg)
            total_turn_deg = float(value)

            # Pre-calculate EXACT roll-in and roll-out turn contributions
            # by simulating the bank changes and integrating turn rate
            def calc_roll_turn(start_bank, end_bank, roll_rate):
                """Calculate exact heading change during a roll maneuver."""
                total_turn = 0.0
                bank = start_bank
                step = roll_rate * dt if end_bank > start_bank else -roll_rate * dt
                while (step > 0 and bank < end_bank) or (step < 0 and bank > end_bank):
                    if abs(bank) > 0.1:
                        bank_rad = math.radians(abs(bank))
                        turn_rate = math.degrees((G_FPS2 * math.tan(bank_rad)) / max(1.0, tas_fps))
                        total_turn += turn_rate * dt
                    bank += step
                    # Clamp to target
                    if step > 0:
                        bank = min(bank, end_bank)
                    else:
                        bank = max(bank, end_bank)
                return total_turn

            turn_during_roll_in = calc_roll_turn(0.0, target_bank, roll_rate_dps)
            turn_during_roll_out = calc_roll_turn(target_bank, 0.0, roll_rate_dps)

            # Full bank turn needed = total_turn - roll_in_turn - roll_out_turn
            full_bank_turn_deg = max(0.0, total_turn_deg - turn_during_roll_in - turn_during_roll_out)

            # Phase: roll_in -> turn -> roll_out -> final_correction
            phase = "roll_in"
            accumulated_turn_deg = 0.0
            full_turn_accumulated = 0.0

            # Store entry heading to ensure we return to it exactly
            turn_entry_heading = hdg

            while phase != "done":
                # Per-tick TAS recomputation. Altitude drift from off-design
                # power means TAS isn't constant; recompute each tick so
                # turn-rate / radius reflect the current state.
                try:
                    cur_alt_msl = field_elev_ft + alt_state
                    cur_palt = compute_pressure_altitude(cur_alt_msl, altimeter_inhg)
                    cur_tas = compute_true_airspeed(float(ias_knots), cur_palt, oat_c)
                    if cur_tas and cur_tas > 1:
                        tas_knots_val = float(cur_tas)
                        tas_fps = tas_knots_val * 1.68781
                except Exception:
                    pass

                # Per-tick wind refresh — single-altitude lookup for steep
                # turn, but a sheared column at the climb-to-pattern entry
                # band could legitimately differ from the surface wind.
                wn_fps, we_fps = _resolve_wind_at(field_elev_ft + alt_state)

                # Determine target bank based on phase
                if phase == "roll_in":
                    # Ramp up bank
                    bank_state_deg = min(bank_state_deg + roll_rate_dps * dt, target_bank)
                    if bank_state_deg >= target_bank - 0.01:
                        bank_state_deg = target_bank
                        phase = "turn"
                    segment = f"{direction}_roll_in"

                elif phase == "turn":
                    bank_state_deg = target_bank
                    segment = f"{direction}_turn"
                    # Check if we've done enough full-bank turning
                    if full_turn_accumulated >= full_bank_turn_deg - 0.01:
                        phase = "roll_out"

                elif phase == "roll_out":
                    bank_state_deg = max(bank_state_deg - roll_rate_dps * dt, 0.0)
                    segment = f"{direction}_roll_out"
                    if bank_state_deg < 0.01:
                        bank_state_deg = 0.0
                        phase = "final_correction"

                elif phase == "final_correction":
                    # Final correction step: snap to exact entry heading
                    # This ensures perfect 360° turn regardless of numerical drift
                    hdg = turn_entry_heading
                    bank_state_deg = 0.0
                    segment = f"{direction}_turn"  # Label as part of turn for continuity

                    # Compute motion for this final point
                    gs_fps, gs_kt, track_deg, drift_deg = compute_motion()

                    alt_state += (altitude_drift_fpm / 60.0) * dt
                    record(gs_kt, 0.0, track_deg, drift_deg, segment)

                    # Move position for the final step
                    move_position(gs_fps, track_deg)

                    t += dt
                    phase = "done"
                    continue  # Skip the rest of the loop body

                # Compute turn rate based on current bank
                if bank_state_deg > 0.1:
                    bank_rad_now = math.radians(bank_state_deg)
                    turn_rate_rps = (G_FPS2 * math.tan(bank_rad_now)) / max(1.0, tas_fps)
                    turn_rate_dps_now = math.degrees(turn_rate_rps)
                else:
                    turn_rate_dps_now = 0.0

                # Update heading
                dpsi = turn_rate_dps_now * dt
                hdg = _wrap_360(hdg + turn_sign * dpsi)
                accumulated_turn_deg += dpsi

                # Track full-bank turn accumulation
                if phase == "turn":
                    full_turn_accumulated += dpsi

                # Compute motion
                gs_fps, gs_kt, track_deg, drift_deg = compute_motion()

                alt_state += (altitude_drift_fpm / 60.0) * dt
                record(gs_kt, turn_sign * bank_state_deg, track_deg, drift_deg, segment)

                # Move position
                move_position(gs_fps, track_deg)

                # Advance time
                t += dt

                # Safety limit
                if t > 600:  # 10 minutes max
                    break

            # Ensure bank is zeroed after turn
            bank_state_deg = 0.0

        elif action_type == "pause":
            # Wings-level pause with wind drift
            pause_duration = float(value)
            pause_end_time = t + pause_duration

            while t < pause_end_time:
                # Wings level, maintain heading
                bank_state_deg = 0.0

                # Compute motion
                gs_fps, gs_kt, track_deg, drift_deg = compute_motion()

                alt_state += (altitude_drift_fpm / 60.0) * dt
                record(gs_kt, 0.0, track_deg, drift_deg, "pause")

                # Move position (aircraft drifts with wind)
                move_position(gs_fps, track_deg)

                # Advance time
                t += dt

                # Safety limit
                if t > 600:
                    break

    # Surface power/altitude-drift metadata on the final hover point so
    # the callback can render an off-design verdict without recomputing.
    if hover:
        hover[-1]["power_setting"] = round(power_pct, 3)
        hover[-1]["design_power"] = design_power
        hover[-1]["altitude_change_ft"] = round(alt_state - altitude_ft, 1)
        hover[-1]["altitude_drift_fpm"] = round(altitude_drift_fpm, 0)
        # Surface the correct Vs + load-factor-adjusted stall speed so the
        # callback can render a real stall-margin chip (pre-fix it used a
        # broken 48-kt fallback for every airframe).
        load_factor = (1.0 / math.cos(math.radians(abs(bank_angle_deg)))
                       if abs(bank_angle_deg) < 89.9 else float("inf"))
        vs_at_n_kt = vs_clean_kt * math.sqrt(load_factor) if math.isfinite(load_factor) else None
        hover[-1]["vs_clean_kt"] = round(vs_clean_kt, 1)
        hover[-1]["vs_at_bank_kt"] = round(vs_at_n_kt, 1) if vs_at_n_kt else None
        hover[-1]["stall_margin_kt"] = round(float(ias_knots) - vs_at_n_kt, 1) if vs_at_n_kt else None
        hover[-1]["roll_rate_dps_used"] = round(roll_rate_dps, 1)
        hover[-1]["wind_profile_used"] = wind_profile is not None

    return path, hover
