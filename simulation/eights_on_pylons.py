"""
Eights on Pylons simulation module.

The wing tip points directly at the pylon throughout the turn.
This means the pylon IS the center of the turn circle.
At pivotal altitude, the wing appears "pinned" to the pylon.
"""
import math

from physics import (
    compute_pressure_altitude,
    compute_true_airspeed,
    G_FPS2,
    FT_PER_NM,
    point_from,
)

from .base import _ref_weight_lb


def _wrap_360(angle: float) -> float:
    """Normalize angle to [0, 360)."""
    return angle % 360.0


def compute_pivotal_altitude(groundspeed_kt: float) -> float:
    """PA = GS² / 11.3 (GS in knots, PA in feet AGL)"""
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
    timestep_sec: float = 0.5,
    entry_direction: str = "downwind",
    # Post-2026-05-21 additions
    wind_profile=None,
    engine_option: str = None,
) -> tuple:
    """
    Simulate Eights on Pylons.

    Wing tip points at pylon = pylon is center of turn.
    Simple figure-8: two circles connected by straight tangent lines.
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
    bank_angle_deg = max(20.0, min(45.0, float(bank_angle_deg or 30.0)))

    if ac is None:
        ac = {}
    if weight_lb is None or weight_lb <= 0:
        weight_lb = ac.get("total_weight_lb") or _ref_weight_lb(ac) or 2300.0
    weight_lb = float(weight_lb)

    # User surface wind authoritative; column drives the single-altitude
    # lookup at maneuver altitude (= pivotal altitude). Pre-fix the sim
    # had no wind_profile support at all.
    if wind_profile is not None:
        try:
            wind_profile = wind_profile.with_surface_override(
                wind_dir_deg, wind_speed_kt,
                surface_alt_ft_msl=field_elev_ft,
            )
            # Pivotal alt is roughly GS²/11.3 — close to IAS²/11.3 for the
            # lookup. We refine after computing TAS below.
            wd, ws = wind_profile.at(field_elev_ft + (ias_knots ** 2) / 11.3)
            wind_dir_deg = float(wd)
            wind_speed_kt = float(ws)
        except Exception:
            pass

    # Weight-interpolated Vs from the aircraft's stall_speeds table.
    # Pre-fix the callback read `stall_speed_clean` (never emitted by
    # this sim) and fell back to 48 kt for every airframe.
    def _vs_clean_kt(ac_dict, weight):
        sd = (ac_dict.get("stall_speeds") or {}).get("clean", {})
        weights = sd.get("weights", [])
        speeds = sd.get("speeds", [])
        if not weights or not speeds:
            return 50.0
        if weight <= weights[0]:
            return float(speeds[0])
        if weight >= weights[-1]:
            return float(speeds[-1])
        for i in range(len(weights) - 1):
            if weights[i] <= weight <= weights[i + 1]:
                r = (weight - weights[i]) / (weights[i + 1] - weights[i])
                return float(speeds[i]) + r * (float(speeds[i + 1]) - float(speeds[i]))
        return float(speeds[-1])

    vs_clean_kt = _vs_clean_kt(ac, weight_lb)

    # Compute TAS and turn radius
    estimated_pa = compute_pivotal_altitude(ias_knots)
    alt_msl_ft = field_elev_ft + estimated_pa
    pressure_alt_ft = compute_pressure_altitude(alt_msl_ft, altimeter_inhg)
    tas_knots = compute_true_airspeed(ias_knots, pressure_alt_ft, oat_c)
    tas_knots = float(tas_knots) if tas_knots and tas_knots > 1 else ias_knots
    tas_fps = tas_knots * 1.68781

    # Wind for groundspeed calc
    wind_to_rad = math.radians(_wrap_360(wind_dir_deg + 180.0))
    wind_fps = wind_speed_kt * 1.68781
    wn_fps = wind_fps * math.cos(wind_to_rad)
    we_fps = wind_fps * math.sin(wind_to_rad)

    # Turn radius (wing tip to pylon distance)
    bank_rad = math.radians(bank_angle_deg)
    turn_radius_ft = (tas_fps ** 2) / (G_FPS2 * math.tan(bank_rad))
    turn_radius_nm = turn_radius_ft / FT_PER_NM

    # Pylon positions
    from geopy import Point
    p1 = Point(pylon1['lat'], pylon1['lon'])
    p2 = Point(pylon2['lat'], pylon2['lon'])

    mid_lat = (pylon1['lat'] + pylon2['lat']) / 2
    ft_per_deg_lat = 364567.2
    ft_per_deg_lon = 364567.2 * math.cos(math.radians(mid_lat))

    pylon_dist_ft = math.hypot(
        (pylon2['lat'] - pylon1['lat']) * ft_per_deg_lat,
        (pylon2['lon'] - pylon1['lon']) * ft_per_deg_lon
    )
    pylon_dist_nm = pylon_dist_ft / FT_PER_NM

    # Bearing P1 to P2
    bearing_to_p2 = _wrap_360(math.degrees(math.atan2(
        (pylon2['lon'] - pylon1['lon']) * ft_per_deg_lon,
        (pylon2['lat'] - pylon1['lat']) * ft_per_deg_lat
    )))

    # P1 = left turn (CCW), P2 = right turn (CW)
    # At any point on circle: heading is tangent, pylon is 90° off (at wing tip)

    # Roll transition arc (degrees) - gradual roll in/out
    roll_arc = 15.0

    # Path and hover data
    path = []
    hover = []
    t = 0.0
    max_gs, min_gs = 0.0, 999.0
    max_pa, min_pa = 0.0, 9999.0

    def get_gs_pa(hdg):
        hdg_rad = math.radians(hdg)
        vg_n = tas_fps * math.cos(hdg_rad) + wn_fps
        vg_e = tas_fps * math.sin(hdg_rad) + we_fps
        gs = math.hypot(vg_n, vg_e) / 1.68781
        track = _wrap_360(math.degrees(math.atan2(vg_e, vg_n)))
        drift = (track - hdg + 540) % 360 - 180
        pa = compute_pivotal_altitude(gs)
        return gs, pa, track, drift

    def add_pt(lat, lon, hdg, seg, aob=0.0):
        nonlocal t, max_gs, min_gs, max_pa, min_pa
        gs, pa, track, drift = get_gs_pa(hdg)
        max_gs, min_gs = max(max_gs, gs), min(min_gs, gs)
        max_pa, min_pa = max(max_pa, pa), min(min_pa, pa)
        lf = 1.0 / math.cos(math.radians(abs(aob))) if abs(aob) > 1 else 1.0
        path.append([lat, lon])
        hover.append({
            "time": round(t, 2), "alt": round(pa, 0), "pivotal_alt": round(pa, 0),
            "tas": round(tas_knots, 1), "ias": round(ias_knots, 1), "gs": round(gs, 1),
            "aob": round(aob, 1), "vs": 0, "track": round(track, 1),
            "heading": round(hdg, 1), "drift": round(drift, 1),
            # `wind_correction` is the magnitude the scrubber tooltip displays
            # (pre-fix it was missing → tooltip showed 0 every tick).
            "wind_correction": round(drift, 1),
            "load_factor": round(lf, 2), "segment": seg,
        })

    def arc(center, start_pos, end_pos, turn_dir, seg, npts=40):
        """Draw arc. turn_dir: -1=CCW/left, +1=CW/right. Pylon at center."""
        nonlocal t
        if turn_dir < 0:  # CCW
            extent = (end_pos - start_pos) % 360 or 360
        else:  # CW
            extent = (start_pos - end_pos) % 360 or 360

        for i in range(npts + 1):
            f = i / npts
            if turn_dir < 0:
                pos = _wrap_360(start_pos + extent * f)
                hdg = _wrap_360(pos + 90)
            else:
                pos = _wrap_360(start_pos - extent * f)
                hdg = _wrap_360(pos - 90)

            pt = point_from(center, pos, turn_radius_nm)

            # Bank: roll in first roll_arc°, roll out last roll_arc°
            prog = extent * f
            if prog < roll_arc:
                aob = bank_angle_deg * (prog / roll_arc) * (-turn_dir)
            elif prog > extent - roll_arc:
                aob = bank_angle_deg * ((extent - prog) / roll_arc) * (-turn_dir)
            else:
                aob = bank_angle_deg * (-turn_dir)

            add_pt(pt.latitude, pt.longitude, hdg, seg, aob)
            if i < npts:
                seg_ft = (extent / npts) * math.pi / 180 * turn_radius_ft
                gs, _, _, _ = get_gs_pa(hdg)
                t += seg_ft / (gs * 1.68781) if gs > 0 else 0.5

    def line(start, end, seg, npts=40):
        """Draw straight line.

        npts bumped from 10 → 40 (post-2026-05-21) so the scrubber on
        the straight tangent feels as smooth as on the arcs (which
        use 40+1 samples). Pre-fix the straights had 11 samples,
        making the airplane marker jump in chunks on the time slider.
        """
        nonlocal t
        dlat = end.latitude - start.latitude
        dlon = end.longitude - start.longitude
        hdg = _wrap_360(math.degrees(math.atan2(dlon * ft_per_deg_lon, dlat * ft_per_deg_lat)))
        dist_ft = math.hypot(dlat * ft_per_deg_lat, dlon * ft_per_deg_lon)

        for i in range(npts + 1):
            f = i / npts
            add_pt(start.latitude + f * dlat, start.longitude + f * dlon, hdg, seg, 0.0)
            if i < npts:
                gs, _, _, _ = get_gs_pa(hdg)
                t += (dist_ft / npts) / (gs * 1.68781) if gs > 0 else 0.5

    # =========================================================================
    # FIGURE-8 GEOMETRY - Internal Tangent
    # =========================================================================
    # P1: CCW (left turn), heading = position + 90
    # P2: CW (right turn), heading = position - 90
    #
    # For internal tangents of two circles with equal radius R, centers D apart:
    # The tangent offset from the center-to-center line is: arcsin(2R/D)
    # This is the angle where arc heading naturally aligns with tangent line bearing.

    bearing_to_p1 = _wrap_360(bearing_to_p2 + 180)

    # Compute internal tangent offset.
    #
    # The internal tangent only exists when the two orbit circles do
    # NOT overlap: pylon_dist > 2 · turn_radius. Near the boundary
    # (D ≈ 2R, sin(α) ≈ 1, α ≈ 90°) the tangent becomes degenerate —
    # the heading the orbit ends at no longer matches the line's
    # geometric direction, which surfaces as a visible altitude /
    # groundspeed step at each transition.
    #
    # We compute a spacing-quality ratio (D/R) so the callback can
    # render an ACS-style warning and suggest a target range. The
    # commercial ACS doesn't give a hard pylon-distance number, but
    # a healthy figure-8 needs ~3-6 turn-radii between pylons so the
    # straight tangent is long enough to roll wings-level briefly
    # without compressing the maneuver.
    d_over_r = (pylon_dist_nm / turn_radius_nm) if turn_radius_nm > 0 else 0.0
    if pylon_dist_nm > 2 * turn_radius_nm:
        tangent_offset = math.degrees(math.asin(2 * turn_radius_nm / pylon_dist_nm))
    else:
        tangent_offset = 30.0  # Fallback if circles overlap — sim still runs but geometry is invalid

    # P1→P2 transition (internal tangent)
    # Tangent line bearing = bearing_to_p2 + tangent_offset
    # On P1 (CCW): heading = position + 90, so position = heading - 90
    p1_exit = _wrap_360(bearing_to_p2 + tangent_offset - 90)
    # On P2 (CW): heading = position - 90, so position = heading + 90
    p2_entry = _wrap_360(bearing_to_p2 + tangent_offset + 90)

    # P2→P1 transition (the other internal tangent)
    # Tangent line bearing = bearing_to_p1 - tangent_offset
    # On P2 (CW): heading = position - 90, so position = heading + 90
    p2_exit = _wrap_360(bearing_to_p1 - tangent_offset + 90)
    # On P1 (CCW): heading = position + 90, so position = heading - 90
    p1_reentry = _wrap_360(bearing_to_p1 - tangent_offset - 90)

    # Entry: start on P1 heading toward P2 (before the tangent offset)
    p1_entry = _wrap_360(bearing_to_p2 - 90)

    # Final tangent points (recompute with final positions)
    p1_entry_pt = point_from(p1, p1_entry, turn_radius_nm)
    p1_exit_pt = point_from(p1, p1_exit, turn_radius_nm)
    p2_entry_pt = point_from(p2, p2_entry, turn_radius_nm)
    p2_exit_pt = point_from(p2, p2_exit, turn_radius_nm)
    p1_reentry_pt = point_from(p1, p1_reentry, turn_radius_nm)

    # Entry approach
    entry_start = point_from(p1_entry_pt, _wrap_360(bearing_to_p2 + 180), 0.3)

    # BUILD PATH
    # 1. Entry to P1
    line(entry_start, p1_entry_pt, "entry")

    # 2. Initial arc on P1 (from entry to exit toward P2)
    arc(p1, p1_entry, p1_exit, -1, "pylon_1_entry")

    # 3. P1 to P2 transition
    line(p1_exit_pt, p2_entry_pt, "transition_p1_to_p2")

    for _ in range(num_eights):
        # 4. Arc around P2 (CW/right)
        arc(p2, p2_entry, p2_exit, +1, "pylon_2")

        # 5. P2 to P1 transition
        line(p2_exit_pt, p1_reentry_pt, "transition_p2_to_p1")

        # 6. Arc around P1 (CCW/left)
        arc(p1, p1_reentry, p1_exit, -1, "pylon_1")

        # Back to P2 if more eights
        if _ < num_eights - 1:
            line(p1_exit_pt, p2_entry_pt, "transition_p1_to_p2")

    # Results
    avg_pa = (max_pa + min_pa) / 2

    # Bank/crab extremes from hover stream.
    banks_seen = [abs(p.get("aob", 0)) for p in hover if p.get("aob") is not None]
    crabs_seen = [abs(p.get("drift", 0)) for p in hover if p.get("drift") is not None]
    max_bank_achieved = max(banks_seen) if banks_seen else bank_angle_deg
    min_bank_achieved = min((b for b in banks_seen if b > 1.0), default=0.0)
    max_crab = max(crabs_seen) if crabs_seen else 0.0

    # Vs at the actual max bank flown.
    load_factor_at_max = (
        1.0 / math.cos(math.radians(max_bank_achieved))
        if max_bank_achieved < 89.9 else float("inf")
    )
    vs_at_max_bank = (
        vs_clean_kt * math.sqrt(load_factor_at_max)
        if math.isfinite(load_factor_at_max) else None
    )

    warnings = {
        "pylon_distance_ft": round(pylon_dist_ft, 0),
        "pylon_distance_nm": round(pylon_dist_nm, 2),
        "turn_radius_ft": round(turn_radius_ft, 0),
        "turn_radius_nm": round(turn_radius_nm, 3),
        "pylon_axis_deg": round(bearing_to_p2, 0),
        "max_groundspeed": round(max_gs, 1),
        "min_groundspeed": round(min_gs, 1),
        "pivotal_alt_max": round(max_pa, 0),
        "pivotal_alt_min": round(min_pa, 0),
        "pivotal_alt_avg": round(avg_pa, 0),
        "pivotal_alt_range": round(max_pa - min_pa, 0),
        "pivotal_alt_no_wind": round(compute_pivotal_altitude(tas_knots), 0),
        "total_time_sec": round(t, 1),
        "weight_lb": round(weight_lb, 0),
        "tas_knots": round(tas_knots, 1),
        "ias_knots": round(ias_knots, 1),
        "bank_angle_target": round(bank_angle_deg, 0),
        "eights_completed": num_eights,
        "p1_turn_direction": "left",
        "p2_turn_direction": "right",
        # Post-2026-05-21 audit additions — fields the callback needs to
        # render a correct stall-margin chip and per-leg/per-bank stats.
        "vs_clean_kt": round(vs_clean_kt, 1),
        "vs_at_max_bank_kt": round(vs_at_max_bank, 1) if vs_at_max_bank else None,
        "stall_speed_clean": round(vs_clean_kt, 1),  # legacy callback key
        "stall_speed_in_turn": round(vs_at_max_bank, 1) if vs_at_max_bank else None,
        "min_ias_achieved": round(ias_knots, 1),
        "max_bank_achieved": round(max_bank_achieved, 1),
        "min_bank_achieved": round(min_bank_achieved, 1),
        "max_crab_angle": round(max_crab, 1),
        "wind_dir": round(wind_dir_deg, 0),
        "wind_speed": round(wind_speed_kt, 0),
        "wind_profile_used": wind_profile is not None,
        "engine_option": engine_option,
    }

    # Pylon-spacing ACS validation (post-2026-05-21 audit). The
    # internal tangent geometry needs D > 2R to exist at all, and
    # D ≥ ~3R to look like a proper figure-8. Beyond ~6R the figure-8
    # stretches and the maneuver loses its rhythm. Surface tier +
    # ideal range so the callback can either error or warn the pilot.
    #
    # IDEAL_MIN / IDEAL_MAX from common GA training references — the
    # commercial ACS itself only says "appropriate pylons", which leaves
    # it to instructor judgment. These thresholds match the practical
    # range CFIs use.
    IDEAL_MIN_RATIO = 3.0
    IDEAL_MAX_RATIO = 6.0
    HARD_MIN_RATIO = 2.0   # below this the tangent geometry breaks
    SOFT_MIN_RATIO = 2.5   # below this the transitions visibly snap
    SOFT_MAX_RATIO = 8.0   # above this the figure-8 is too stretched

    if d_over_r < HARD_MIN_RATIO:
        warnings["pylon_spacing_tier"] = "error"
        warnings["pylon_spacing_error"] = (
            f"Pylons too close: distance {pylon_dist_nm:.2f} NM = {d_over_r:.1f}× "
            f"turn radius {turn_radius_nm:.2f} NM. Orbits overlap — "
            f"figure-8 geometry is impossible. Need ≥ {HARD_MIN_RATIO:.0f}× turn radius "
            f"({HARD_MIN_RATIO * turn_radius_nm:.2f} NM minimum)."
        )
    elif d_over_r < SOFT_MIN_RATIO:
        warnings["pylon_spacing_tier"] = "error"
        warnings["pylon_spacing_error"] = (
            f"Pylons too close: {d_over_r:.1f}× turn radius. "
            f"Internal tangent is degenerate — altitude/groundspeed will jump at "
            f"each transition. Move pylons farther apart "
            f"({IDEAL_MIN_RATIO * turn_radius_nm:.2f}-{IDEAL_MAX_RATIO * turn_radius_nm:.2f} NM is ideal)."
        )
    elif d_over_r < IDEAL_MIN_RATIO:
        warnings["pylon_spacing_tier"] = "warning"
        warnings["pylon_spacing_warning"] = (
            f"Pylons close: {d_over_r:.1f}× turn radius. Straight tangent is brief — "
            f"consider {IDEAL_MIN_RATIO:.0f}-{IDEAL_MAX_RATIO:.0f}× ideal "
            f"({IDEAL_MIN_RATIO * turn_radius_nm:.2f}-{IDEAL_MAX_RATIO * turn_radius_nm:.2f} NM)."
        )
    elif d_over_r > SOFT_MAX_RATIO:
        warnings["pylon_spacing_tier"] = "warning"
        warnings["pylon_spacing_warning"] = (
            f"Pylons far apart: {d_over_r:.1f}× turn radius. Figure-8 stretches — "
            f"ACS expects a coherent figure-8 rhythm. Consider "
            f"{IDEAL_MIN_RATIO * turn_radius_nm:.2f}-{IDEAL_MAX_RATIO * turn_radius_nm:.2f} NM."
        )
    elif d_over_r > IDEAL_MAX_RATIO:
        warnings["pylon_spacing_tier"] = "warning"
        warnings["pylon_spacing_warning"] = (
            f"Pylons stretching: {d_over_r:.1f}× turn radius. "
            f"{IDEAL_MIN_RATIO:.0f}-{IDEAL_MAX_RATIO:.0f}× is the ideal training range."
        )
    else:
        warnings["pylon_spacing_tier"] = "ok"

    warnings["pylon_spacing_ratio"] = round(d_over_r, 2)
    warnings["pylon_spacing_ideal_min_nm"] = round(IDEAL_MIN_RATIO * turn_radius_nm, 2)
    warnings["pylon_spacing_ideal_max_nm"] = round(IDEAL_MAX_RATIO * turn_radius_nm, 2)

    return path, hover, warnings
