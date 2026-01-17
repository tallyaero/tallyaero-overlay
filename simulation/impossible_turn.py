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
    centerline_xtol_ft: float = 150.0,
    max_time_sec: float = 240.0,
    intercept_angle_deg: float = 25.0,
    xtrack_align_gate_ft: float = 1000.0,
    along_align_gate_ft: float = 2000.0,
    jink_bank_cap_deg: float = 30.0,
    jink_hdg_tol_deg: float = 30.0,
    jink_xtrack_tol_ft: float = 50.0,
    bank_response_tau_sec: float = 2.0,
    straight_track_bank_cap_deg: float = 15.0,
    xtrack_intercept_scale_ft: float = 1300.0,
    intercept_max_deg: float = 45.0,
):
    """Internal function to run a single impossible turn simulation."""
    dt = float(timestep_sec) if timestep_sec and timestep_sec > 0 else 0.5

    _centerline_xtol_ft = float(centerline_xtol_ft)
    _align_window_deg = float(align_window_deg)

    runway_hdg = _wrap_360(float(runway_heading_deg))
    hdg = runway_hdg

    final_course_hdg = _wrap_360(runway_hdg + 180.0)

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

    def wind_corrected_heading_for_track(desired_track_deg: float, tas_fps: float) -> float:
        trk = math.radians(_wrap_360(desired_track_deg))
        w_cross = (-wn_fps * math.sin(trk)) + (we_fps * math.cos(trk))
        ratio = 0.0
        if tas_fps > 1.0:
            ratio = max(-1.0, min(1.0, w_cross / tas_fps))
        wca = math.asin(ratio)
        hdg_out = _wrap_360(desired_track_deg + math.degrees(wca))
        return hdg_out

    def record(gs_kt, aob_deg, vs_fpm, track_deg, drift_deg=None):
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

        xtrack_ft, along_ft = _cross_track_to_centerline_ft(start_point, cur, final_course_hdg)
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
            desired_track_deg = final_course_hdg
            bank_target_deg = abs(min(abs(float(bank_deg)), abs(float(jink_bank_cap_deg))))
            sign = sign_turn2

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
            hdg_cmd = wind_corrected_heading_for_track(final_course_hdg, tas_fps)
            hdg_err = _angle_diff_deg(hdg_cmd, hdg)
            hdg_step = max(-max_hdg_rate_dps * dt, min(max_hdg_rate_dps * dt, hdg_err))
            hdg = _wrap_360(hdg + hdg_step)

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

        vs_fps = tas_fps / glide_eff
        alt -= vs_fps * dt
        vs_fpm = vs_fps * 60.0

        record(
            gs_kt=gs_kt,
            aob_deg=(aob if abs(aob) > 0.1 else 0.0),
            vs_fpm=vs_fpm,
            track_deg=track_deg,
            drift_deg=drift_deg,
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
            if captured:
                return path, hover, _finalize_meta(
                    success=True,
                    reason="touchdown_after_capture",
                    impact_marker=(cur.latitude, cur.longitude),
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
            intercept_offset = -max(-1.0, min(1.0, float(xtrack_ft) / float(xtrack_intercept_scale_ft))) * float(intercept_max_deg)
            intercept_trk = _wrap_360(final_course_hdg + intercept_offset)
            intercept_err = abs(_angle_diff_deg(intercept_trk, track_deg))

            if total_turn_1 >= float(min_turn_deg_before_capture) and intercept_err <= float(intercept_angle_deg):
                phase = "straight"

        elif phase == "straight":
            if along_ft > 0.0:
                if align_err <= float(align_window_deg) and abs(xtrack_ft) <= float(centerline_xtol_ft):
                    captured = True
                    if captured_at_time is None:
                        captured_at_time = float(t)
                    phase = "final"
                else:
                    if abs(xtrack_ft) <= float(xtrack_align_gate_ft) and float(along_ft) >= float(along_align_gate_ft):
                        phase = "turn2"

        elif phase == "turn2":
            hdg_tol = min(float(align_window_deg), float(jink_hdg_tol_deg)) if float(jink_hdg_tol_deg) > 0 else float(align_window_deg)
            xtol = min(float(centerline_xtol_ft), float(jink_xtrack_tol_ft)) if float(jink_xtrack_tol_ft) > 0 else float(centerline_xtol_ft)

            if align_err <= hdg_tol and abs(xtrack_ft) <= xtol and along_ft > 0.0:
                captured = True
                if captured_at_time is None:
                    captured_at_time = float(t)
                phase = "final"

            if abs(xtrack_ft) <= float(centerline_xtol_ft) and align_err <= float(align_window_deg) and along_ft > 0.0:
                captured = True
                if captured_at_time is None:
                    captured_at_time = float(t)
                phase = "final"

        step_nm = (gs_fps * dt) / FT_PER_NM
        cur = point_from(cur, track_deg, step_nm)

        xtrack_ft, along_ft = _cross_track_to_centerline_ft(start_point, cur, final_course_hdg)
        align_err = abs(_angle_diff_deg(track_deg, final_course_hdg))

        t += dt

    xtrack_ft, along_ft = _cross_track_to_centerline_ft(start_point, cur, final_course_hdg)
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
    xtrack_align_gate_ft: float = 600.0,
    along_align_gate_ft: float = 2000.0,
    jink_bank_cap_deg: float = 15.0,
    jink_hdg_tol_deg: float = 3.0,
    jink_xtrack_tol_ft: float = 50.0,
    find_min_alt: bool = True,
    min_alt_floor_agl: float = 100.0,
    max_alt_ceiling_agl: float = 2000.0,
    min_alt_resolution_ft: float = 10.0,
):
    """
    Simulate impossible turn maneuver.

    Returns (path, hover, meta) where meta includes success status and min_feasible_alt_agl.
    """
    if start_point is None:
        return [], [], {"success": False, "reason": "no_start_point"}

    if ac is None:
        return [], [], {"success": False, "reason": "no_aircraft_data"}

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

    def eval_at(alt_agl: float, intercept_bank_deg: float):
        return _run_impossible_turn_once(
            start_point=start_point,
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

    def find_best_bank_for_alt(alt_agl: float):
        best_fail = None

        b = float(bank_min_deg)
        bmax = float(bank_max_deg)
        bstep = max(0.1, float(bank_step_deg))

        while b <= bmax + 1e-9:
            path, hover, meta = eval_at(alt_agl, b)
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

    path = best_run["path"]
    hover = best_run["hover"]
    meta = best_run["meta"] if isinstance(best_run["meta"], dict) else {}

    meta["bank_deg"] = float(best_run["bank"])
    meta["jink_bank_cap_deg"] = float(jink_bank_cap_deg)
    meta["flap_config"] = str(flap_config)
    meta["prop_config"] = str(prop_config)

    min_feasible = None
    if find_min_alt:
        low = float(min_alt_floor_agl)
        high = float(max_alt_ceiling_agl)
        res = max(1.0, float(min_alt_resolution_ft))

        hi_run = find_best_bank_for_alt(high)
        if hi_run and hi_run["meta"].get("success", False):
            lo_run = find_best_bank_for_alt(low)
            if lo_run and lo_run["meta"].get("success", False):
                min_feasible = low
            else:
                while (high - low) > res:
                    mid = 0.5 * (low + high)
                    mid_run = find_best_bank_for_alt(mid)
                    if mid_run and mid_run["meta"].get("success", False):
                        high = mid
                    else:
                        low = mid
                min_feasible = high

    meta["min_feasible_alt_agl"] = min_feasible
    return path, hover, meta
