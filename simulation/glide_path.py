"""
Power-Off 180 glide path simulation module.
"""
import math
import numpy as np
from geopy import Point as GeoPoint
from geopy.distance import geodesic as geo_dist, distance

from physics import (
    compute_pressure_altitude, compute_air_density, compute_true_airspeed,
    compute_glide_ratio, adjust_glide_ratio_for_density, compute_turn_radius,
    compute_required_bank, compute_load_factor, knots_to_fps, g,
    point_from, calculate_initial_compass_bearing
)


def find_required_aob_for_arc_fit(
    arc_start,
    arc_angle_rad,  # kept for compatibility, not used
    target_point,
    start_heading,
    turn_dir,
    tas_knots,
    max_bank_deg=60,
    tolerance_pct=0.002,
    roll_in_correction_total=0.0  # kept for compatibility, not used
):
    """
    Returns (best_aob_deg, best_arc_angle_deg) that best fits the chord.
    """
    if isinstance(turn_dir, str):
        td = turn_dir.strip().lower()
        turn_dir = -1 if td.startswith("l") else 1
    else:
        turn_dir = -1 if float(turn_dir) < 0 else 1

    g_mps2 = 9.80665
    tas_mps = float(tas_knots) * 0.514444

    def compute_turn_radius_m(aob_deg: float) -> float:
        aob_deg = max(0.1, float(aob_deg))
        return (tas_mps ** 2) / (g_mps2 * math.tan(math.radians(aob_deg)))

    def arc_endpoint(center_radius_m: float, arc_angle_deg: float, entry_heading_deg: float):
        center_bearing = (float(entry_heading_deg) + turn_dir * 90.0) % 360.0
        center = geo_dist(meters=center_radius_m).destination(arc_start, center_bearing)
        start_angle = calculate_initial_compass_bearing(center, arc_start)
        end_angle = (start_angle + turn_dir * float(arc_angle_deg)) % 360.0
        return geo_dist(meters=center_radius_m).destination(center, end_angle)

    chord_dist_m = geo_dist(
        (arc_start.latitude, arc_start.longitude),
        (target_point.latitude, target_point.longitude)
    ).meters

    tolerance_m = max(min(chord_dist_m * float(tolerance_pct), 5.0), 1.0)

    best_aob = None
    best_arc_angle_deg = None
    best_error = float("inf")

    for aob in np.arange(5.0, float(max_bank_deg) + 0.0001, 0.05):
        Rm = compute_turn_radius_m(aob)
        ratio = chord_dist_m / max(2.0 * Rm, 1e-6)
        ratio = max(0.0, min(1.0, ratio))

        arc_rad = 2.0 * math.asin(ratio)
        arc_rad = min(arc_rad, math.radians(175.0))
        arc_deg = math.degrees(arc_rad)

        endpoint = arc_endpoint(Rm, arc_deg, start_heading)
        error = geo_dist(
            (endpoint.latitude, endpoint.longitude),
            (target_point.latitude, target_point.longitude)
        ).meters

        if error < best_error:
            best_error = error
            best_aob = float(aob)
            best_arc_angle_deg = float(arc_deg)

        if error <= tolerance_m:
            break

    return (best_aob if best_aob is not None else float(max_bank_deg),
            best_arc_angle_deg if best_arc_angle_deg is not None else 90.0)


def simulate_glide_path_to_target(
    start_point,
    start_heading,
    touchdown_point,
    touchdown_heading,
    ac,
    engine_option,
    weight_lbs,
    flap_config,
    prop_config,
    oat_c,
    altimeter_inhg,
    wind_dir,
    wind_speed,
    start_ias_kias,
    altitude_agl,
    pattern_dir,
    selected_airport_elev_ft,
    max_bank_deg=45,
    timestep_sec=0.5,
):
    """
    Power-Off 180 glide model with THREE segments:
      1) Straight downwind at start_heading
      2) Constant-bank turn (higher sink)
      3) Straight final at touchdown_heading
    """
    # Basic guards
    if start_point is None or touchdown_point is None:
        return [], [], None
    if altitude_agl is None or altitude_agl <= 0:
        start_latlon = [start_point.latitude, start_point.longitude]
        hover = [{
            "alt": 0.0, "tas": 0.0, "time": 0.0, "aob": 0.0, "vs": 0.0,
            "segment": "ground", "track": start_heading, "heading": start_heading, "drift": 0.0,
        }]
        return [start_latlon], hover, start_latlon

    # Aircraft best glide + base glide ratio
    if ac.get("engine_count", 1) > 1:
        perf_block = ac["engine_options"][engine_option]["oei_performance"][f"{flap_config}_up"][prop_config]
        best_glide_kias = perf_block["best_glide_speed_kias"]
        base_glide_ratio = ac["single_engine_limits"]["best_glide_ratio"]
    else:
        best_glide_kias = ac["single_engine_limits"]["best_glide"]
        base_glide_ratio = ac["single_engine_limits"]["best_glide_ratio"]

    gear_type = ac.get("gear_type", "fixed")

    # Environment
    field_elev_ft = float(selected_airport_elev_ft or 0.0)
    alt_msl_ft = field_elev_ft + float(altitude_agl or 0.0)
    pressure_alt_ft = compute_pressure_altitude(alt_msl_ft, float(altimeter_inhg))
    rho = compute_air_density(pressure_alt_ft, float(oat_c))

    # Straight-flight glide ratio
    straight_gr = compute_glide_ratio(base_glide_ratio, flap_config, gear_type, prop_config)
    straight_gr = adjust_glide_ratio_for_density(straight_gr, rho)
    straight_gr = max(3.0, min(straight_gr, 25.0))

    ias_for_geometry = float(start_ias_kias or best_glide_kias)
    tas_knots = compute_true_airspeed(ias_for_geometry, pressure_alt_ft, float(oat_c))
    tas_fps = max(1.0, knots_to_fps(tas_knots))

    # Arc geometry
    heading_vec = ((touchdown_heading - start_heading + 540.0) % 360.0) - 180.0
    arc_angle_deg_geom = max(abs(heading_vec), 5.0)
    arc_angle_rad_geom = math.radians(arc_angle_deg_geom)

    chord_m = geo_dist(
        (start_point.latitude, start_point.longitude),
        (touchdown_point.latitude, touchdown_point.longitude),
    ).meters

    bank_deg = max_bank_deg
    if chord_m > 1.0 and math.sin(arc_angle_rad_geom / 2.0) > 1e-6:
        R_geom_m = chord_m / (2.0 * math.sin(arc_angle_rad_geom / 2.0))
        R_geom_ft = R_geom_m / 0.3048
        bank_from_geom = compute_required_bank(tas_knots, R_geom_ft)
        bank_deg = min(max_bank_deg, max(5.0, bank_from_geom))
    bank_rad = math.radians(bank_deg)

    R_turn_ft = compute_turn_radius(tas_knots, bank_deg)

    if pattern_dir == "left":
        delta = (start_heading - touchdown_heading + 360.0) % 360.0
        if delta > 180.0:
            delta -= 360.0
        arc_angle_deg = abs(delta)
        turn_sign = -1.0
    else:
        delta = (touchdown_heading - start_heading + 360.0) % 360.0
        if delta > 180.0:
            delta -= 360.0
        arc_angle_deg = abs(delta)
        turn_sign = 1.0

    arc_angle_deg = min(180.0, arc_angle_deg if arc_angle_deg > 1.0 else 180.0)
    arc_angle_rad = math.radians(arc_angle_deg)

    n = compute_load_factor(bank_deg)
    turn_gr = straight_gr / n
    turn_gr = max(2.0, min(turn_gr, straight_gr))

    arc_length_ft = R_turn_ft * arc_angle_rad
    alt_loss_turn_ft = arc_length_ft / turn_gr

    h0 = altitude_agl
    L_dw_ft = 0.0
    L_fn_ft = 0.0

    if alt_loss_turn_ft >= h0:
        frac = max(0.0, min(1.0, h0 / alt_loss_turn_ft))
        arc_angle_rad *= frac
        arc_angle_deg *= frac
        arc_length_ft *= frac
    else:
        h_rem = h0 - alt_loss_turn_ft
        h_dw = h_rem * 0.5
        h_fn = h_rem - h_dw
        L_dw_ft = h_dw * straight_gr
        L_fn_ft = h_fn * straight_gr

    wind_speed_knots = float(wind_speed or 0.0)

    def drift_corrected(wind_from_deg, track_hdg_deg):
        if wind_speed_knots <= 0.1:
            return tas_knots, track_hdg_deg, 0.0
        wind_to_deg = (wind_from_deg + 180.0) % 360.0
        alpha_deg = (wind_to_deg - track_hdg_deg + 360.0) % 360.0
        alpha = math.radians(alpha_deg)
        cross = wind_speed_knots * math.sin(alpha)
        head = wind_speed_knots * math.cos(alpha)
        cross_clamped = max(min(cross, tas_knots * 0.99), -tas_knots * 0.99)
        drift_rad = math.asin(cross_clamped / tas_knots)
        drift_deg = math.degrees(drift_rad)
        heading_deg = (track_hdg_deg + drift_deg + 360.0) % 360.0
        along_air = tas_knots * math.cos(drift_rad)
        gs_knots = along_air + head
        gs_knots = max(5.0, gs_knots)
        return gs_knots, heading_deg, drift_deg

    path = []
    hover = []
    lat = start_point.latitude
    lon = start_point.longitude
    alt_ft = h0
    time_s = 0.0
    dist_dw_ft = 0.0
    dist_arc_ft = 0.0
    dist_fn_ft = 0.0
    arc_accum_deg = 0.0

    if L_dw_ft > 1.0:
        segment = "downwind"
    elif arc_length_ft > 1.0:
        segment = "arc"
    else:
        segment = "final"

    impact_marker = None
    max_steps = 4000

    for _ in range(max_steps):
        if segment == "downwind":
            track_hdg = start_heading
            seg_gr = straight_gr
            aob_geom = 0.0
        elif segment == "arc":
            track_hdg = start_heading + turn_sign * arc_accum_deg
            seg_gr = turn_gr
            aob_geom = bank_deg
        else:
            track_hdg = touchdown_heading
            seg_gr = straight_gr
            aob_geom = 0.0

        track_hdg = (track_hdg + 360.0) % 360.0
        ds_ft = tas_fps * timestep_sec
        if ds_ft <= 0.1:
            break

        gs_knots, heading_deg, drift_deg = drift_corrected(wind_dir, track_hdg)
        gs_fps = knots_to_fps(gs_knots)
        dt = ds_ft / gs_fps if gs_fps > 1e-3 else timestep_sec

        dh_ft = ds_ft / seg_gr
        alt_ft = max(0.0, alt_ft - dh_ft)

        ds_nm = ds_ft / 6076.12
        new_point = point_from(GeoPoint(lat, lon), track_hdg, ds_nm)
        lat, lon = new_point.latitude, new_point.longitude

        time_s += dt

        if segment == "downwind":
            dist_dw_ft += ds_ft
            if dist_dw_ft >= L_dw_ft and arc_length_ft > 1.0:
                segment = "arc"
        elif segment == "arc":
            dist_arc_ft += ds_ft
            dpsi_rad = ds_ft / R_turn_ft
            arc_accum_deg += math.degrees(dpsi_rad)
            if arc_accum_deg >= arc_angle_deg or dist_arc_ft >= arc_length_ft:
                segment = "final"
        else:
            dist_fn_ft += ds_ft

        vs_fpm = -(dh_ft / dt) * 60.0 if dt > 1e-3 else 0.0

        if segment == "arc":
            gs_fps_for_bank = knots_to_fps(gs_knots)
            bank_eff_rad = math.atan((gs_fps_for_bank ** 2) / (g * max(R_turn_ft, 1.0)))
            aob_display = math.degrees(bank_eff_rad)
        else:
            aob_display = 0.0

        path.append([lat, lon])
        hover.append({
            "alt": alt_ft, "tas": tas_knots, "time": time_s, "aob": aob_display,
            "vs": vs_fpm, "segment": segment, "track": track_hdg,
            "heading": heading_deg, "drift": drift_deg, "gs": gs_knots,
        })

        dist_to_td_ft = geo_dist(
            (lat, lon),
            (touchdown_point.latitude, touchdown_point.longitude)
        ).feet

        if segment == "final" and dist_to_td_ft <= max(150.0, ds_ft * 1.5):
            lat = touchdown_point.latitude
            lon = touchdown_point.longitude
            alt_ft = 0.0
            time_s += dt
            vs_fpm = -(dh_ft / dt) * 60.0 if dt > 1e-3 else 0.0
            path.append([lat, lon])
            hover.append({
                "alt": alt_ft, "tas": tas_knots, "time": time_s, "aob": 0.0,
                "vs": vs_fpm, "segment": "final", "track": touchdown_heading,
                "heading": heading_deg, "drift": drift_deg, "gs": gs_knots,
            })
            impact_marker = None
            break

        if alt_ft <= 0.0:
            dist_to_td_ft = geo_dist(
                (lat, lon),
                (touchdown_point.latitude, touchdown_point.longitude)
            ).feet
            snap_radius_ft = max(300.0, ds_ft * 2.0)

            if segment == "final" and dist_to_td_ft <= snap_radius_ft:
                lat = touchdown_point.latitude
                lon = touchdown_point.longitude
                alt_ft = 0.0
                time_s += dt
                path.append([lat, lon])
                hover.append({
                    "alt": alt_ft, "tas": tas_knots, "time": time_s, "aob": 0.0,
                    "vs": vs_fpm, "segment": "final", "track": touchdown_heading,
                    "heading": heading_deg, "drift": drift_deg, "gs": gs_knots,
                })
                impact_marker = None
            else:
                impact_marker = [lat, lon]
            break

        if segment == "final" and dist_fn_ft > max(L_fn_ft * 1.5, 3 * straight_gr * h0):
            impact_marker = [lat, lon]
            break

    return path, hover, impact_marker
