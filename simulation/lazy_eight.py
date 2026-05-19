"""
Lazy Eight simulation module.

A lazy eight is a maneuver designed to develop perfect coordination of controls
through a wide range of airspeeds and altitudes. It consists of two 180-degree
turns in opposite directions while making a climb and descent during each turn.

Reference: FAA Airplane Flying Handbook (FAA-H-8083-3C), Chapter 10

FAA ACS Standards (Commercial Pilot - FAA-S-ACS-7):
- Entry: Straight and level at maneuvering speed (Va) or manufacturer recommended
- Power: Cruise power maintained throughout
- Bank angle at 45°/135° points: approximately 15°
- Bank angle at 90° point: approximately 30° (maximum)
- Pitch at 45° point: maximum nose-up (~10°)
- Pitch at 90° point: level (passing through horizon)
- Pitch at 135° point: maximum nose-down (~5-7°)
- Airspeed at 90° point: minimum (5-10 knots above stall)
- At 180° point: wings level, entry altitude ±100 ft, entry airspeed ±10 kts
- Heading tolerance: ±10° at each 180° point
- Minimum altitude: 1,500 ft AGL

The maneuver forms a horizontal figure-8 when viewed from above, with the
aircraft climbing during the first 90° of each turn and descending during
the second 90°.
"""
import math
from geopy import Point as GeoPoint

from physics import (
    compute_pressure_altitude,
    compute_true_airspeed,
    point_from,
    G_FPS2,
    FT_PER_NM,
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
    """
    if not ac:
        return 48.0

    stall_data = ac.get("stall_speeds", {}).get(config, {})
    weights = stall_data.get("weights", [])
    speeds = stall_data.get("speeds", [])

    if not weights or not speeds or len(weights) != len(speeds):
        sel = ac.get("single_engine_limits", {})
        vs = sel.get("vs", sel.get("vs0", 48.0))
        return float(vs) if vs else 48.0

    if weight_lb <= weights[0]:
        return float(speeds[0])
    if weight_lb >= weights[-1]:
        return float(speeds[-1])

    for i in range(len(weights) - 1):
        if weights[i] <= weight_lb <= weights[i + 1]:
            ratio = (weight_lb - weights[i]) / (weights[i + 1] - weights[i])
            vs = speeds[i] + ratio * (speeds[i + 1] - speeds[i])
            return float(vs)

    return float(speeds[-1])


def simulate_lazy_eight(
    entry_point: dict,
    entry_heading_deg: float,
    first_turn_direction: str,
    entry_altitude_ft: float,
    entry_ias_knots: float,
    max_bank_angle_deg: float = 30.0,
    wind_dir_deg: float = 0.0,
    wind_speed_kt: float = 0.0,
    oat_c: float = 15.0,
    altimeter_inhg: float = 29.92,
    field_elev_ft: float = 0.0,
    ac: dict = None,
    weight_lb: float = None,
    timestep_sec: float = 0.5,
    power_setting: float = 0.625,
    wind_profile=None,
) -> tuple:
    """
    Simulate a lazy eight maneuver with proper wind effects and aircraft data.

    The lazy eight consists of two 180° turns in opposite directions:
    - First turn: climb to peak altitude at 90°, descend back to entry altitude at 180°
    - Second turn: same pattern in opposite direction

    Per FAA AFH (FAA-H-8083-3C):
    - Bank angle varies sinusoidally: 0° -> 15° (45°) -> 30° (90°) -> 15° (135°) -> 0° (180°)
    - Pitch varies: 0° -> +10° (45°) -> 0° (90°) -> -7° (135°) -> 0° (180°)
    - Airspeed: entry speed -> min at 90° (5-10 kt above stall) -> entry speed at 180°

    Args:
        entry_point: Dict with 'lat' and 'lon' keys
        entry_heading_deg: Entry heading in degrees (true)
        first_turn_direction: 'left' or 'right' for first 180° turn
        entry_altitude_ft: Entry altitude in feet AGL
        entry_ias_knots: Entry indicated airspeed in knots (typically Va)
        max_bank_angle_deg: Maximum bank angle at 90° point (default 30° per ACS)
        wind_dir_deg: Wind direction (FROM) in degrees
        wind_speed_kt: Wind speed in knots
        oat_c: Outside air temperature in Celsius
        altimeter_inhg: Altimeter setting in inches Hg
        field_elev_ft: Field elevation in feet MSL
        ac: Aircraft data dict (for stall speeds)
        weight_lb: Aircraft weight in pounds
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
    max_bank_angle_deg = float(max_bank_angle_deg or 30.0)
    entry_heading_deg = _wrap_360(float(entry_heading_deg or 0.0))
    wind_dir_deg = float(wind_dir_deg or 0.0)

    # Phase H — when a column profile is provided, use its mid-altitude
    # wind. Lazy 8 oscillates ±500 ft, so the maneuver's effective
    # column average is the entry altitude.
    if wind_profile is not None:
        try:
            mean_alt_msl = float(field_elev_ft) + float(entry_altitude_ft)
            wd_eff, ws_eff = wind_profile.at(mean_alt_msl)
            wind_dir_deg = float(wd_eff)
            wind_speed_kt = float(ws_eff)
        except Exception:
            pass
    wind_speed_kt = float(wind_speed_kt or 0.0)
    oat_c = float(oat_c if oat_c is not None else 15.0)
    altimeter_inhg = float(altimeter_inhg if altimeter_inhg is not None else 29.92)
    field_elev_ft = float(field_elev_ft or 0.0)

    # Get aircraft weight
    if weight_lb is None and ac:
        weight_lb = ac.get("max_takeoff_weight", ac.get("gross_weight", 2300.0))
    elif weight_lb is None:
        weight_lb = 2300.0
    weight_lb = float(weight_lb)

    # Get stall speed for minimum airspeed reference
    vs_clean = _interpolate_stall_speed(ac, weight_lb, "clean")
    # Target minimum speed at 90° point: 5-10 knots above stall (use 7 as middle)
    min_ias_target = vs_clean + 7.0

    # Compute initial TAS
    alt_msl_ft = field_elev_ft + entry_altitude_ft
    pressure_alt_ft = compute_pressure_altitude(alt_msl_ft, altimeter_inhg)
    entry_tas_knots = compute_true_airspeed(entry_ias_knots, pressure_alt_ft, oat_c)
    entry_tas_knots = float(entry_tas_knots) if entry_tas_knots and entry_tas_knots > 1 else entry_ias_knots

    # Wind components
    wn_fps, we_fps = _wind_components_from_dir(wind_dir_deg, wind_speed_kt)

    # Initialize state
    cur = GeoPoint(entry_point["lat"], entry_point["lon"])
    hdg = entry_heading_deg
    alt_agl = entry_altitude_ft
    ias = entry_ias_knots
    t = 0.0

    path = []
    hover = []

    # Lazy eight parameters per FAA AFH
    # Bank angle profile: sinusoidal, peaks at 90°
    # Pitch profile: +10° at 45°, 0° at 90°, -7° at 135°
    max_pitch_up = 10.0  # degrees at 45° point
    max_pitch_down = 7.0  # degrees at 135° point

    # Estimate altitude gain at 90° point
    # Based on energy trade: kinetic -> potential
    # Altitude gain ≈ (V_entry² - V_min²) / (2g)
    # For typical GA: entry at 100 kt, min at 55 kt -> ~400-600 ft gain
    ias_delta = entry_ias_knots - min_ias_target
    # Rough estimate: ~10 ft altitude gain per knot of speed lost
    estimated_alt_gain = ias_delta * 10.0
    estimated_alt_gain = max(200.0, min(800.0, estimated_alt_gain))  # Reasonable bounds

    # Design Directive — Lazy 8 design power = 0.625 (cruise). Off-design
    # power drifts oscillation amplitude per:
    #   amplitude_factor = 1.0 + abs(power_setting - 0.625) * 0.5
    # So at 100% power amplitude grows 1.19x, at 30% power 1.16x. The
    # altitude-target and IAS-target swings are scaled by this factor —
    # the figure-8 develops bigger climbs and steeper dives.
    try:
        power_pct = float(power_setting) if power_setting is not None else 0.625
    except (TypeError, ValueError):
        power_pct = 0.625
    power_pct = max(0.0, min(1.0, power_pct))
    design_power = 0.625
    amplitude_factor = 1.0 + abs(power_pct - design_power) * 0.5
    estimated_alt_gain = estimated_alt_gain * amplitude_factor

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

    def record(gs_kt, aob_deg, vs_fpm, track_deg, drift_deg, pitch_deg, segment, turn_progress):
        """Record a point in path and hover data."""
        load_factor = 1.0 / math.cos(math.radians(aob_deg)) if abs(aob_deg) < 89.9 else None
        hover.append({
            "time": round(t, 2),
            "alt": round(alt_agl, 1),
            "tas": round(tas, 1),
            "ias": round(ias, 1),
            "gs": round(gs_kt, 1),
            "aob": round(aob_deg, 1),
            "load_factor": round(load_factor, 2) if load_factor is not None else None,
            "vs": round(vs_fpm, 0),
            "track": round(track_deg, 1),
            "heading": round(hdg, 1),
            "drift": round(drift_deg, 1) if drift_deg is not None else 0.0,
            "pitch": round(pitch_deg, 1),
            "segment": segment,
            "turn_progress": round(turn_progress, 1),
            "vs_ref": round(vs_clean, 1),
            "speed_margin": round(ias - vs_clean, 1),
        })
        path.append([cur.latitude, cur.longitude])

    def get_lazy_eight_parameters(turn_progress_deg: float) -> tuple:
        """
        Get bank angle, pitch, and target IAS based on progress through turn.

        Per FAA AFH (FAA-H-8083-3C):
        - Bank: 0° at 0°, 15° at 45°, 30° at 90°, 15° at 135°, 0° at 180°
        - Pitch: 0° at 0°, +10° at 45°, 0° at 90°, -7° at 135°, 0° at 180°
        - IAS: entry at 0°, min at 90°, entry at 180°
        - Alt: entry at 0°, max at 90°, entry at 180°

        Args:
            turn_progress_deg: Progress through the 180° turn (0 to 180)

        Returns:
            (bank_angle, pitch_angle, target_ias, target_alt_offset)
        """
        progress = min(180.0, max(0.0, turn_progress_deg))
        progress_rad = math.radians(progress)

        # Bank angle: LINEAR/TRIANGULAR profile per ACS
        # ACS specifies: 0° at entry, ~15° at 45°, ~30° at 90°, ~15° at 135°, 0° at 180°
        # This is a triangular profile, NOT sinusoidal
        if progress <= 90.0:
            # Linear increase from 0 to max_bank over 0-90°
            bank = max_bank_angle_deg * (progress / 90.0)
        else:
            # Linear decrease from max_bank to 0 over 90-180°
            bank = max_bank_angle_deg * ((180.0 - progress) / 90.0)

        # Pitch angle: more complex profile
        # 0° -> +10° at 45° -> 0° at 90° -> -7° at 135° -> 0° at 180°
        # Model as: pitch_up * sin(2*progress) for first half,
        #           pitch_down * sin(2*(progress-90)) for second half
        if progress <= 90.0:
            # First half: climbing, pitch goes up then down
            # Peak pitch-up at 45°
            pitch = max_pitch_up * math.sin(2.0 * progress_rad)
        else:
            # Second half: descending, pitch goes down then up
            # Peak pitch-down at 135°
            pitch = -max_pitch_down * math.sin(2.0 * (progress_rad - math.pi / 2))

        # IAS profile: sinusoidal decrease to min at 90°
        # IAS = entry_ias - (entry_ias - min_ias) * sin(progress)
        ias_range = entry_ias_knots - min_ias_target
        target_ias = entry_ias_knots - ias_range * math.sin(progress_rad)

        # Altitude profile: sinusoidal increase to max at 90°
        # Alt offset = max_gain * sin(progress)
        alt_offset = estimated_alt_gain * math.sin(progress_rad)

        return bank, pitch, target_ias, alt_offset

    # Execute two 180° turns - track ACTUAL heading change to drive progress
    turn_directions = []
    if str(first_turn_direction).lower().startswith('l'):
        turn_directions = [-1.0, 1.0]  # Left then right
    else:
        turn_directions = [1.0, -1.0]  # Right then left

    for turn_num, turn_sign in enumerate(turn_directions):
        segment_base = f"turn{turn_num + 1}"

        # Store entry state for this turn
        turn_entry_heading = hdg
        turn_entry_alt = alt_agl
        turn_entry_ias = ias

        # Track actual heading change (accumulated turn)
        accumulated_turn = 0.0

        # Bootstrap bank to get turns started quickly (per FAA: "immediately")
        bootstrap_bank = 8.0  # degrees - enough to get meaningful turn rate

        while accumulated_turn < 172.0:  # Stop early to allow snappy transition
            # Use ACTUAL accumulated heading change to drive parameters
            turn_progress_deg = min(180.0, accumulated_turn)

            # Get target parameters based on actual turn progress
            target_bank, target_pitch, target_ias, target_alt_offset = get_lazy_eight_parameters(turn_progress_deg)

            # Bootstrap: ramp up bank quickly at start and maintain minimum at end
            # This ensures turns begin/end "immediately" per FAA AFH
            if accumulated_turn < 15.0:
                # Quick ramp from bootstrap to natural bank profile at start
                ramp_factor = accumulated_turn / 15.0
                natural_bank = target_bank
                target_bank = bootstrap_bank + (natural_bank - bootstrap_bank) * ramp_factor
                target_bank = max(target_bank, bootstrap_bank * (1.0 - ramp_factor * 0.5))
            elif accumulated_turn > 160.0:
                # Maintain minimum bank near end to complete turn quickly
                remaining = 172.0 - accumulated_turn
                min_end_bank = bootstrap_bank * 0.6 * (remaining / 12.0)  # Keep some bank
                target_bank = max(target_bank, min_end_bank + 2.0)  # At least 2° bank

            # Determine segment name based on progress
            if turn_progress_deg < 45.0:
                segment = f"{segment_base}_0-45"
            elif turn_progress_deg < 90.0:
                segment = f"{segment_base}_45-90"
            elif turn_progress_deg < 135.0:
                segment = f"{segment_base}_90-135"
            else:
                segment = f"{segment_base}_135-180"

            # Compute current TAS
            tas = compute_tas_from_ias(ias, alt_agl)
            tas_fps = tas * 1.68781

            # Compute turn rate from bank and TAS
            if target_bank > 0.1:
                bank_rad = math.radians(target_bank)
                turn_rate_rps = (G_FPS2 * math.tan(bank_rad)) / max(1.0, tas_fps)
                turn_rate_dps = math.degrees(turn_rate_rps)
            else:
                turn_rate_dps = 0.0

            # Update heading based on actual turn rate
            dpsi = turn_rate_dps * dt
            hdg = _wrap_360(hdg + turn_sign * dpsi)
            accumulated_turn += dpsi

            # Smoothly transition IAS toward target
            ias_error = target_ias - ias
            ias_rate = ias_error * 0.3  # knots per second convergence rate
            ias += ias_rate * dt
            ias = max(min_ias_target * 0.95, ias)  # Don't go below stall margin

            # Smoothly transition altitude toward target
            target_alt = turn_entry_alt + target_alt_offset
            alt_error = target_alt - alt_agl
            # Calculate vertical speed to reach target
            vs_fpm = alt_error * 60.0 * 0.2  # Smooth convergence
            vs_fpm = max(-1500.0, min(1500.0, vs_fpm))  # Reasonable VS limits

            # Update altitude
            alt_agl += (vs_fpm / 60.0) * dt

            # Compute motion
            gs_fps, gs_kt, track_deg, drift_deg = compute_motion(tas)

            # Record point (apply turn_sign to bank for L/R display)
            record(gs_kt, turn_sign * target_bank, vs_fpm, track_deg, drift_deg, target_pitch, segment, turn_progress_deg)

            # Move position
            step_ft = gs_fps * dt
            step_nm = step_ft / FT_PER_NM
            cur = point_from(cur, track_deg, step_nm)

            # Advance time
            t += dt

            # Safety limit
            if t > 180:  # 3 minutes max for full lazy eight
                break

        # At 180° point - snap heading and continue immediately
        # Per FAA AFH: "a climbing turn should be started immediately in the opposite direction"
        target_180_heading = _wrap_360(turn_entry_heading + turn_sign * 180.0)
        hdg = target_180_heading

        # Reset altitude and airspeed to entry values (per ACS tolerances)
        alt_agl = turn_entry_alt
        ias = turn_entry_ias

        # Record ONE transition point at 180° - no pause, immediate reversal
        tas = compute_tas_from_ias(ias, alt_agl)
        gs_fps, gs_kt, track_deg, drift_deg = compute_motion(tas)
        record(gs_kt, 0.0, 0.0, track_deg, drift_deg, 0.0, f"{segment_base}_180", 180.0)

        # Check safety limit
        if t > 180:
            break

    # Surface power / amplitude-drift metadata on the last hover point so
    # the callback can render an off-design verdict in D2.
    if hover:
        alts = [pt.get("alt", entry_altitude_ft) for pt in hover]
        last = hover[-1]
        last["power_setting"] = round(power_pct, 3)
        last["design_power"] = design_power
        last["amplitude_factor"] = round(amplitude_factor, 3)
        last["altitude_swing_ft"] = round(max(alts) - min(alts), 1)

    return path, hover
