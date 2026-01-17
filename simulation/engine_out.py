"""
Engine-out glide simulation module.
"""
import math
import numpy as np
from geopy import Point as GeoPoint
from geopy.distance import geodesic as geo_dist, distance

from physics import (
    compute_pressure_altitude, compute_air_density, compute_true_airspeed,
    compute_glide_ratio, adjust_glide_ratio_for_density, compute_turn_radius,
    compute_load_factor, knots_to_fps, g, FT_PER_NM,
    point_from, calculate_initial_compass_bearing,
    FINAL_MIN_DIST_NM, FINAL_MAX_DIST_NM, FINAL_CROSSING_HEIGHT_FT
)

from .glide_path import simulate_glide_path_to_target


def simulate_tight_overhead_orbit(
    start_lat,
    start_lon,
    alt_ft,
    tas_knots,
    straight_gr,
    bank_deg,
    turn_sign,
    entry_track_hdg,
    wind_dir,
    wind_speed_knots,
    timestep_sec=0.5,
    required_alt_loss_ft=None,
):
    """
    One constant-radius 360° orbit around a center placed on the runway side of downwind.
    """
    g_local = 32.174
    tas_fps = tas_knots * 1.68781

    bank_deg = float(bank_deg)
    bank_deg = max(10.0, min(60.0, bank_deg))
    bank_rad = math.radians(bank_deg)

    R_ft = (tas_fps ** 2) / (g_local * math.tan(bank_rad))

    n_orbit = compute_load_factor(bank_deg)
    turn_gr_orbit = straight_gr / max(n_orbit, 1.0)
    turn_gr_orbit = max(2.0, min(turn_gr_orbit, straight_gr))

    start_pt = GeoPoint(start_lat, start_lon)
    center_bearing = (entry_track_hdg + turn_sign * 90.0) % 360.0
    center = geo_dist(feet=R_ft).destination(start_pt, center_bearing)

    start_angle = calculate_initial_compass_bearing(center, start_pt)

    ds_ft = tas_fps * timestep_sec
    if ds_ft <= 0.1:
        return [[start_lat, start_lon]], [], alt_ft, 0.0

    if required_alt_loss_ft is None:
        arc_angle_rad = 2.0 * math.pi
    else:
        arc_angle_rad = required_alt_loss_ft * turn_gr_orbit / max(R_ft, 1.0)
        arc_angle_rad = max(0.0, min(arc_angle_rad, 2.0 * math.pi))

    arc_length_ft = R_ft * arc_angle_rad
    n_steps = max(1, int(arc_length_ft / ds_ft))

    if n_steps <= 0 or arc_angle_rad <= 0.0:
        return [[start_lat, start_lon]], [], alt_ft, 0.0

    dtheta_rad = arc_angle_rad / n_steps
    dtheta_deg = math.degrees(dtheta_rad) * turn_sign

    wind_speed = float(wind_speed_knots or 0.0)

    def drift_corrected(track_hdg_deg):
        if wind_speed <= 0.1:
            return tas_knots, track_hdg_deg, 0.0
        wind_from_deg = wind_dir
        wind_to_deg = (wind_from_deg + 180.0) % 360.0
        alpha_deg = (wind_to_deg - track_hdg_deg + 360.0) % 360.0
        alpha = math.radians(alpha_deg)
        cross = wind_speed * math.sin(alpha)
        head = wind_speed * math.cos(alpha)
        cross_clamped = max(min(cross, tas_knots * 0.99), -tas_knots * 0.99)
        drift_rad = math.asin(cross_clamped / tas_knots)
        drift_deg = math.degrees(drift_rad)
        heading_deg = (track_hdg_deg + drift_deg + 360.0) % 360.0
        along_air = tas_knots * math.cos(drift_rad)
        gs_knots = along_air + head
        gs_knots = max(5.0, gs_knots)
        return gs_knots, heading_deg, drift_deg

    path = [[start_lat, start_lon]]
    hover = []
    time_s = 0.0
    h = alt_ft
    angle = start_angle

    for _ in range(n_steps):
        angle = (angle + dtheta_deg) % 360.0
        track_hdg = (angle + 90.0 * turn_sign) % 360.0

        ds_step_ft = R_ft * abs(dtheta_rad)
        gs_knots, heading_deg, drift_deg = drift_corrected(track_hdg)
        gs_fps = knots_to_fps(gs_knots)
        dt = ds_step_ft / gs_fps if gs_fps > 1e-3 else timestep_sec

        dh_ft = ds_step_ft / turn_gr_orbit
        h = max(0.0, h - dh_ft)

        ds_nm = ds_step_ft / 6076.12
        cur_pt = GeoPoint(path[-1][0], path[-1][1])
        new_pt = distance(nautical=ds_nm).destination(cur_pt, track_hdg)

        path.append([new_pt.latitude, new_pt.longitude])
        time_s += dt

        vs_fpm = -(dh_ft / dt) * 60.0 if dt > 1e-3 else 0.0

        bank_eff_rad = math.atan((gs_fps ** 2) / (g_local * max(R_ft, 1.0)))
        aob_display = math.degrees(bank_eff_rad)

        hover.append({
            "alt": h, "tas": tas_knots, "time": time_s, "aob": aob_display,
            "vs": vs_fpm, "segment": "engineout", "track": track_hdg,
            "heading": heading_deg, "drift": drift_deg, "gs": gs_knots,
            "note": "tight_orbit",
        })

        if h <= 0.0:
            break

    return path, hover, h, time_s


def simulate_engineout_glide(
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
    touchdown_elev_ft,
    selected_airport_elev_ft,
    pattern_dir="left",
    max_bank_deg=45,
    timestep_sec=0.5,
):
    """
    Engine-out glide simulation with tight overhead orbit capability.
    """
    if start_point is None or touchdown_point is None:
        return [], [], None
    if altitude_agl is None or altitude_agl <= 0:
        sp = [start_point.latitude, start_point.longitude]
        hover = [{
            "alt": 0.0, "tas": 0.0, "time": 0.0, "aob": 0.0, "vs": 0.0,
            "segment": "ground", "track": 0.0, "heading": 0.0, "drift": 0.0, "gs": 0.0,
        }]
        return [sp], hover, sp

    # Performance first
    if ac.get("engine_count", 1) > 1:
        perf_block = ac["engine_options"][engine_option]["oei_performance"][f"{flap_config}_up"][prop_config]
        best_glide_kias = perf_block["best_glide_speed_kias"]
        base_glide_ratio = ac["single_engine_limits"]["best_glide_ratio"]
    else:
        best_glide_kias = ac["single_engine_limits"]["best_glide"]
        base_glide_ratio = ac["single_engine_limits"]["best_glide_ratio"]

    gear_type = ac.get("gear_type", "fixed")

    # Environment
    field_elev_ft = float(touchdown_elev_ft or 0.0)
    alt_msl_ft = field_elev_ft + float(altitude_agl or 0.0)
    pressure_alt_ft = compute_pressure_altitude(alt_msl_ft, float(altimeter_inhg))
    rho = compute_air_density(pressure_alt_ft, float(oat_c))

    # Glide + TAS
    straight_gr = compute_glide_ratio(base_glide_ratio, flap_config, gear_type, prop_config)
    straight_gr = adjust_glide_ratio_for_density(straight_gr, rho)
    straight_gr = max(3.0, min(straight_gr, 25.0))

    tas_knots = compute_true_airspeed(best_glide_kias, pressure_alt_ft, float(oat_c))
    tas_fps = max(1.0, knots_to_fps(tas_knots))

    LOWKEY_MIN_DIST_FT = FINAL_MIN_DIST_NM * 6076.12
    LOWKEY_MAX_DIST_FT = FINAL_MAX_DIST_NM * 6076.12
    ORBIT_ONSET_RATIO = 2.0

    LOWKEY_ALT_MIN_FT = 300.0
    LOWKEY_ALT_MAX_FT = 1500.0

    NEAR_PATTERN_MAX_DIST_FT = LOWKEY_MAX_DIST_FT * 2.0
    MIN_PO180_ALT_FT = 700.0

    turn_sign = -1.0 if pattern_dir == "left" else +1.0

    if pattern_dir == "left":
        abeam_ref_bearing = (touchdown_heading - 90.0) % 360.0
    else:
        abeam_ref_bearing = (touchdown_heading + 90.0) % 360.0

    downwind_track = (touchdown_heading + 180.0) % 360.0
    wind_speed_knots = float(wind_speed or 0.0)

    def drift_corrected(track_hdg_deg):
        if wind_speed_knots <= 0.1:
            return tas_knots, track_hdg_deg, 0.0
        wind_from_deg = wind_dir
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

    def shortest_angle_diff(a, b):
        return (a - b + 180.0) % 360.0 - 180.0

    def blend_heading(base_hdg, target_hdg, weight):
        diff = shortest_angle_diff(target_hdg, base_hdg)
        return (base_hdg + weight * diff + 360.0) % 360.0

    path = []
    hover = []

    lat = start_point.latitude
    lon = start_point.longitude
    alt_ft = float(altitude_agl or 0.0)
    initial_alt = max(alt_ft, 1.0)
    time_s = 0.0
    max_steps = 8000
    impact_marker = None
    did_tight_orbit = False
    ABEAM_LOCKOUT = False

    path.append([lat, lon])
    hover.append({
        "alt": alt_ft, "tas": tas_knots, "time": time_s, "aob": 0.0, "vs": 0.0,
        "segment": "engineout", "track": 0.0, "heading": 0.0, "drift": 0.0,
        "gs": 0.0, "note": "start",
    })

    while max_steps > 0:
        max_steps -= 1

        dist_to_td_ft = geo_dist(
            (lat, lon),
            (touchdown_point.latitude, touchdown_point.longitude)
        ).feet

        track_to_td = calculate_initial_compass_bearing(
            GeoPoint(lat, lon), touchdown_point
        )
        radial_bearing = calculate_initial_compass_bearing(
            touchdown_point, GeoPoint(lat, lon)
        )

        near_pattern = dist_to_td_ft <= NEAR_PATTERN_MAX_DIST_FT
        enough_alt_for_po180 = alt_ft >= MIN_PO180_ALT_FT

        if alt_ft > FINAL_CROSSING_HEIGHT_FT:
            R_energy = (alt_ft - FINAL_CROSSING_HEIGHT_FT) * straight_gr
        else:
            R_energy = LOWKEY_MIN_DIST_FT

        R_des = max(LOWKEY_MIN_DIST_FT, min(LOWKEY_MAX_DIST_FT, R_energy))

        dist_err_ft = dist_to_td_ft - R_des
        max_err_ft = max(R_des, 1.0)
        err_norm = max(-1.0, min(1.0, dist_err_ft / max_err_ft))

        in_lowkey_band = LOWKEY_ALT_MIN_FT <= alt_ft <= LOWKEY_ALT_MAX_FT

        R_bank_ft = (tas_fps ** 2) / (g * math.tan(math.radians(max_bank_deg)))
        R_orbit_ft = max(LOWKEY_MIN_DIST_FT, min(R_des, R_bank_ft))

        n_orbit = compute_load_factor(max_bank_deg)
        turn_gr_orbit = straight_gr / max(n_orbit, 1.0)
        turn_gr_orbit = max(2.0, min(turn_gr_orbit, straight_gr))

        orbit_circ_ft = 2.0 * math.pi * R_orbit_ft
        alt_for_orbit_ft = orbit_circ_ft / max(turn_gr_orbit, 1.0)

        alt_margin_ft = 100.0
        have_energy_for_orbit = alt_ft >= (alt_for_orbit_ft + alt_margin_ft)

        dist_ratio = dist_to_td_ft / max(R_des, 1.0)
        f_orbit = 1.0 - dist_ratio / ORBIT_ONSET_RATIO
        f_orbit = max(0.0, min(1.0, f_orbit))

        H_direct = track_to_td
        H_tangent = (radial_bearing + 90.0 * turn_sign) % 360.0

        tight_orbit_active = (
            have_energy_for_orbit
            and not in_lowkey_band
            and (0.5 * R_des <= dist_to_td_ft <= 1.5 * R_des)
        )

        if tight_orbit_active:
            target_radius_ft = R_orbit_ft
            dist_err_tight = dist_to_td_ft - target_radius_ft
            max_err_tight = max(target_radius_ft, 1.0)
            err_norm_tight = max(-1.0, min(1.0, dist_err_tight / max_err_tight))

            base_hdg = H_tangent

            inward_hdg = (radial_bearing + 180.0) % 360.0
            outward_hdg = radial_bearing
            target_radial_hdg = inward_hdg if dist_err_tight > 0.0 else outward_hdg

            BASE_RADIAL_WEIGHT_TIGHT = 0.7
            MAX_RADIAL_WEIGHT_TIGHT = 0.95

            radial_weight_tight = BASE_RADIAL_WEIGHT_TIGHT * abs(err_norm_tight)
            radial_weight_tight = max(0.0, min(MAX_RADIAL_WEIGHT_TIGHT, radial_weight_tight))

            track_hdg = blend_heading(base_hdg, target_radial_hdg, radial_weight_tight)
        else:
            base_hdg = blend_heading(H_direct, H_tangent, f_orbit)

            inward_hdg = (radial_bearing + 180.0) % 360.0
            outward_hdg = radial_bearing
            target_radial_hdg = inward_hdg if dist_err_ft > 0.0 else outward_hdg

            BASE_RADIAL_WEIGHT = 0.3
            EXTRA_NEAR_GROUND = 0.4 * (1.0 - max(0.0, min(1.0, alt_ft / initial_alt)))
            MAX_RADIAL_WEIGHT = 0.9

            radial_weight = (BASE_RADIAL_WEIGHT + EXTRA_NEAR_GROUND) * abs(err_norm) * f_orbit
            radial_weight = max(0.0, min(MAX_RADIAL_WEIGHT, radial_weight))

            track_hdg = blend_heading(base_hdg, target_radial_hdg, radial_weight)

        track_hdg = (track_hdg + 360.0) % 360.0

        bank_min = 0.0
        bank_max = float(max_bank_deg or 30.0)
        bank_max = max(10.0, bank_max)

        R_for_bank = max(LOWKEY_MIN_DIST_FT, min(LOWKEY_MAX_DIST_FT, R_des))
        bank_rad_nominal = math.atan((tas_fps ** 2) / (g * R_for_bank))
        bank_deg_nominal = math.degrees(bank_rad_nominal)

        bank_deg = bank_deg_nominal * f_orbit
        bank_deg = max(bank_min, min(bank_max, bank_deg))

        n = compute_load_factor(bank_deg if bank_deg > 0 else 0.0)
        turn_gr = straight_gr / max(n, 1.0)
        turn_gr = max(2.0, min(turn_gr, straight_gr)) if bank_deg > 0.5 else straight_gr

        gs_knots, heading_deg, drift_deg = drift_corrected(track_hdg)
        gs_fps = knots_to_fps(gs_knots)

        ds_ft = tas_fps * timestep_sec
        if ds_ft <= 0.1:
            break
        dt = ds_ft / gs_fps if gs_fps > 1e-3 else timestep_sec

        dh_ft = ds_ft / turn_gr
        alt_ft = max(0.0, alt_ft - dh_ft)

        ds_nm = ds_ft / 6076.12
        new_pt = point_from(GeoPoint(lat, lon), track_hdg, ds_nm)
        lat, lon = new_pt.latitude, new_pt.longitude

        time_s += dt
        vs_fpm = -(dh_ft / dt) * 60.0 if dt > 1e-3 else 0.0

        if bank_deg > 0.5:
            bank_eff_rad = math.atan((gs_fps ** 2) / (g * max(R_for_bank, 1.0)))
            aob_display = math.degrees(bank_eff_rad)
        else:
            aob_display = 0.0

        path.append([lat, lon])
        hover.append({
            "alt": alt_ft, "tas": tas_knots, "time": time_s, "aob": aob_display,
            "vs": vs_fpm, "segment": "engineout", "track": track_hdg,
            "heading": heading_deg, "drift": drift_deg, "gs": gs_knots,
        })

        if alt_ft <= 0.0:
            impact_marker = [lat, lon]
            return path, hover, impact_marker

        # Recompute for abeam logic
        dist_to_td_ft = geo_dist(
            (lat, lon),
            (touchdown_point.latitude, touchdown_point.longitude)
        ).feet

        R_bank_ft = (tas_fps ** 2) / (g * math.tan(math.radians(max_bank_deg)))
        R_orbit_ft = max(LOWKEY_MIN_DIST_FT, min(R_des, R_bank_ft))

        n_orbit = compute_load_factor(max_bank_deg)
        turn_gr_orbit = straight_gr / max(n_orbit, 1.0)
        turn_gr_orbit = max(2.0, min(turn_gr_orbit, straight_gr))

        orbit_circ_ft = 2.0 * math.pi * R_orbit_ft
        alt_for_orbit_ft = orbit_circ_ft / max(turn_gr_orbit, 1.0)
        alt_margin_ft = 100.0

        have_energy_for_orbit = alt_ft >= (alt_for_orbit_ft + alt_margin_ft)
        in_lowkey_band = LOWKEY_ALT_MIN_FT <= alt_ft <= LOWKEY_ALT_MAX_FT

        should_handoff_to_po180 = (
            near_pattern
            and enough_alt_for_po180
            and (
                in_lowkey_band
                or not have_energy_for_orbit
                or (did_tight_orbit and alt_ft <= LOWKEY_ALT_MAX_FT + 500.0)
            )
        )

        ABEAM_TOL_DEG = 15.0
        abeam_err = abs(shortest_angle_diff(radial_bearing, abeam_ref_bearing))
        on_abeam_side = abeam_err <= ABEAM_TOL_DEG
        far_enough_out = dist_to_td_ft >= LOWKEY_MIN_DIST_FT * 1.2

        if ABEAM_LOCKOUT and abeam_err > (ABEAM_TOL_DEG + 20.0):
            ABEAM_LOCKOUT = False

        if near_pattern and on_abeam_side and far_enough_out:
            if have_energy_for_orbit and not in_lowkey_band and not did_tight_orbit and not ABEAM_LOCKOUT:
                lowkey_mid = 0.5 * (LOWKEY_ALT_MIN_FT + LOWKEY_ALT_MAX_FT)
                alt_target = min(
                    max(lowkey_mid, LOWKEY_ALT_MIN_FT + 100.0),
                    alt_ft - 100.0,
                )
                needed_loss = max(50.0, alt_ft - alt_target)

                did_tight_orbit = True
                ABEAM_LOCKOUT = True

                best_bank = None
                best_err = float("inf")

                for aob in np.linspace(10.0, max_bank_deg, 80):
                    bank_rad_candidate = math.radians(aob)
                    n_cand = compute_load_factor(aob)
                    turn_gr_cand = straight_gr / max(n_cand, 1.0)
                    turn_gr_cand = max(2.0, min(turn_gr_cand, straight_gr))

                    R_ft_cand = (tas_fps ** 2) / (g * math.tan(bank_rad_candidate))
                    circ_ft = 2.0 * math.pi * R_ft_cand
                    loss_cand = circ_ft / max(turn_gr_cand, 1.0)

                    err = abs(loss_cand - needed_loss)
                    if err < best_err:
                        best_err = err
                        best_bank = aob

                if best_bank is None:
                    best_bank = min(max_bank_deg, 30.0)

                orbit_path, orbit_hover, alt_ft_out, dt_orbit = simulate_tight_overhead_orbit(
                    start_lat=lat,
                    start_lon=lon,
                    alt_ft=alt_ft,
                    tas_knots=tas_knots,
                    straight_gr=straight_gr,
                    bank_deg=best_bank,
                    turn_sign=turn_sign,
                    entry_track_hdg=track_hdg,
                    wind_dir=wind_dir,
                    wind_speed_knots=wind_speed_knots,
                    timestep_sec=timestep_sec,
                    required_alt_loss_ft=needed_loss,
                )

                if len(orbit_path) > 1:
                    for p in orbit_path[1:]:
                        path.append(p)
                for h in orbit_hover:
                    h["time"] += time_s
                    hover.append(h)

                if orbit_path:
                    lat, lon = orbit_path[-1]
                alt_ft = alt_ft_out
                time_s += dt_orbit

                if alt_ft <= 0.0:
                    impact_marker = path[-1]
                    return path, hover, impact_marker

                continue

            if should_handoff_to_po180:
                hover[-1]["note"] = "PO180_handoff"
                po180_path, po180_hover, impact_po = simulate_glide_path_to_target(
                    start_point=GeoPoint(lat, lon),
                    start_heading=downwind_track,
                    touchdown_point=touchdown_point,
                    touchdown_heading=touchdown_heading,
                    ac=ac,
                    engine_option=engine_option,
                    weight_lbs=weight_lbs,
                    flap_config=flap_config,
                    prop_config=prop_config,
                    oat_c=oat_c,
                    altimeter_inhg=altimeter_inhg,
                    wind_dir=wind_dir,
                    wind_speed=wind_speed,
                    start_ias_kias=best_glide_kias,
                    altitude_agl=alt_ft,
                    pattern_dir=pattern_dir,
                    selected_airport_elev_ft=selected_airport_elev_ft,
                    max_bank_deg=max_bank_deg,
                    timestep_sec=timestep_sec,
                )

                if po180_path and po180_hover:
                    path.extend(po180_path[1:])
                    hover.extend(po180_hover[1:])
                    return path, hover, impact_po

    impact_marker = [lat, lon]
    return path, hover, impact_marker
