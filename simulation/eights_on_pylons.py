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

    def line(start, end, seg, npts=10):
        """Draw straight line."""
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

    # Compute internal tangent offset
    if pylon_dist_nm > 2 * turn_radius_nm:
        tangent_offset = math.degrees(math.asin(2 * turn_radius_nm / pylon_dist_nm))
    else:
        tangent_offset = 30.0  # Fallback if circles overlap

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
    }

    return path, hover, warnings
