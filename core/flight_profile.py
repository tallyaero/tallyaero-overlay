"""Climb / cruise / descent flight profile for a planned route.

Real flights aren't flat cruise slabs. An engine-out at the
departure end is a very different reach problem than an engine-out
at top of climb. This module computes altitude as a function of
distance-from-departure so the corridor + divert reach pinch
correctly at the route endpoints.

Public API:
    climb_rate_fpm(climb_ias_kt, vy_kt, vno_kt, baseline_fpm) -> float
        Parabolic falloff from the per-class baseline at Vy to zero at
        Vno. At IAS <= Vy, returns ~95% of baseline (climb rate is
        nearly flat between Vx and Vy in most singles).

    class_baseline_climb_rate(aircraft_dict) -> float
        Per-aircraft-type starting climb rate (fpm). Used until a
        per-aircraft POH climb rate lands in shared-data.

    compute_flight_profile(...)  -> FlightProfile
        Computes TOC / TOD distances given climb + descent assumptions
        and the route's total NM. If the climb + descent legs together
        exceed the route, returns a "no cruise" profile where the
        aircraft cruises at the highest altitude it can reach.

    altitude_at_distance(d_from_dep_nm, profile) -> float
        Returns MSL altitude at any distance along the route.

Descent is fixed at the standard 3-degree glideslope (~318 NM per
1000 ft of descent), back-calculated from the destination so the
descent ends at destination field elevation.
"""
from __future__ import annotations

from dataclasses import dataclass


FT_PER_NM = 6076.115


def class_baseline_climb_rate(aircraft: dict) -> float:
    """Class-default climb rate in fpm. Until shared-data ships a
    per-aircraft `climb_rate_fpm`, infer from type + engine count."""
    ac_type = (aircraft.get("type") or "").lower()
    if "jet" in ac_type:
        return 2000.0
    if "turboprop" in ac_type or "turbine" in ac_type:
        return 1500.0
    if (aircraft.get("engine_count") or 1) >= 2:
        return 1000.0   # piston twin
    return 700.0        # piston single


def climb_rate_fpm(
    climb_ias_kt: float,
    vy_kt: float,
    vno_kt: float,
    baseline_fpm: float,
) -> float:
    """Parabolic falloff from baseline at Vy to zero at Vno.
    Below Vy the rate stays ~95% (most singles climb similarly Vx vs Vy).
    """
    if baseline_fpm <= 0 or vy_kt <= 0:
        return max(0.0, baseline_fpm)
    if climb_ias_kt <= 0:
        return baseline_fpm
    if climb_ias_kt < vy_kt:
        return baseline_fpm * 0.95
    if vno_kt <= vy_kt:
        return baseline_fpm   # weird data; don't divide by zero
    frac = (climb_ias_kt - vy_kt) / (vno_kt - vy_kt)
    frac = max(0.0, min(1.0, frac))
    return baseline_fpm * (1.0 - frac * frac)


@dataclass
class FlightProfile:
    """Computed climb/cruise/descent profile for a route.

    All altitudes in feet MSL. Distances in NM. Speeds in kt.
    `d_toc_nm` and `d_tod_nm` are distance-from-departure of the
    top-of-climb and top-of-descent points respectively.
    """
    field_dep_ft: float
    field_dest_ft: float
    cruise_alt_msl_ft: float
    actual_cruise_alt_msl_ft: float   # may be < cruise target if no room
    total_route_nm: float
    climb_ias_kt: float
    climb_rate_fpm: float
    climb_gs_kt: float                # ground speed during climb
    descent_gs_kt: float
    descent_gradient_deg: float
    d_toc_nm: float                   # 0 if route too short to climb
    d_tod_nm: float                   # total_route if no descent
    has_cruise: bool                  # True if d_toc < d_tod

    def to_dict(self) -> dict:
        return {
            "field_dep_ft": round(self.field_dep_ft, 0),
            "field_dest_ft": round(self.field_dest_ft, 0),
            "cruise_alt_msl_ft": round(self.cruise_alt_msl_ft, 0),
            "actual_cruise_alt_msl_ft": round(self.actual_cruise_alt_msl_ft, 0),
            "total_route_nm": round(self.total_route_nm, 1),
            "climb_ias_kt": round(self.climb_ias_kt, 0),
            "climb_rate_fpm": round(self.climb_rate_fpm, 0),
            "climb_gs_kt": round(self.climb_gs_kt, 0),
            "descent_gs_kt": round(self.descent_gs_kt, 0),
            "descent_gradient_deg": round(self.descent_gradient_deg, 1),
            "d_toc_nm": round(self.d_toc_nm, 1),
            "d_tod_nm": round(self.d_tod_nm, 1),
            "has_cruise": self.has_cruise,
        }


def compute_flight_profile(
    field_dep_ft: float,
    field_dest_ft: float,
    cruise_alt_msl_ft: float,
    total_route_nm: float,
    climb_ias_kt: float,
    climb_rate_fpm: float,
    cruise_tas_kt: float,
    descent_gradient_deg: float = 3.0,
) -> FlightProfile:
    """Compute TOC / TOD given route inputs.

    If the climb + descent demands exceed `total_route_nm` the aircraft
    can't reach the target cruise altitude. We back-solve a reduced
    `actual_cruise_alt` that just barely allows TOC = TOD at the
    midpoint, so the profile is a continuous climb-then-descent with
    no level segment. `has_cruise` is set False in that case.
    """
    # Clamp absurd inputs so we never divide by zero
    climb_ias_kt = max(20.0, climb_ias_kt)
    climb_rate_fpm = max(50.0, climb_rate_fpm)
    cruise_tas_kt = max(20.0, cruise_tas_kt)
    cruise_alt_msl_ft = max(field_dep_ft, cruise_alt_msl_ft)
    total_route_nm = max(0.1, total_route_nm)

    # Climb ground speed ≈ TAS at climb altitude. For our v1 we use
    # IAS as an OK approximation (low altitude climb, no wind component
    # plumbed in yet — wind affects ground reach but not the time profile).
    climb_gs_kt = climb_ias_kt
    descent_gs_kt = cruise_tas_kt   # typical: power-back descent at cruise

    # Distance to climb from dep field to cruise altitude.
    climb_alt_gain_ft = max(0.0, cruise_alt_msl_ft - field_dep_ft)
    climb_time_min = climb_alt_gain_ft / climb_rate_fpm if climb_rate_fpm > 0 else 0
    climb_nm = climb_time_min / 60.0 * climb_gs_kt

    # Standard descent: cot(gradient) NM per ft of altitude lost.
    # At 3 deg: tan(3 deg) = 0.0524 → 1 NM forward per 318 ft down →
    # NM_per_1000ft = 1000 / (FT_PER_NM × tan(3 deg)) ≈ 3.14.
    import math
    nm_per_ft_descent = 1.0 / (FT_PER_NM * math.tan(math.radians(descent_gradient_deg)))
    descent_alt_loss_ft = max(0.0, cruise_alt_msl_ft - field_dest_ft)
    descent_nm = descent_alt_loss_ft * nm_per_ft_descent

    if climb_nm + descent_nm <= total_route_nm:
        # Normal case: there's a cruise segment in the middle.
        d_toc_nm = climb_nm
        d_tod_nm = total_route_nm - descent_nm
        actual_cruise = cruise_alt_msl_ft
        has_cruise = True
    else:
        # Route too short to reach cruise alt. Climb meets descent
        # somewhere short of the target. Solve for actual cruise:
        #   climb_alt_gain / climb_rate × climb_gs / 60
        #   + descent_alt_loss × nm_per_ft_descent
        #   = total_route_nm
        # where climb_alt_gain = actual - field_dep and
        # descent_alt_loss = actual - field_dest.
        # Solving for actual:
        #   actual × (climb_gs/(climb_rate*60) + nm_per_ft_descent)
        #     = total + field_dep × climb_gs/(climb_rate*60)
        #             + field_dest × nm_per_ft_descent
        k_climb = climb_gs_kt / (climb_rate_fpm * 60.0)
        denom = k_climb + nm_per_ft_descent
        if denom <= 0:
            actual_cruise = max(field_dep_ft, field_dest_ft)
        else:
            actual_cruise = (total_route_nm
                             + field_dep_ft * k_climb
                             + field_dest_ft * nm_per_ft_descent) / denom
        actual_cruise = max(field_dep_ft, field_dest_ft, actual_cruise)
        d_toc_nm = (actual_cruise - field_dep_ft) * k_climb
        d_tod_nm = d_toc_nm
        has_cruise = False

    return FlightProfile(
        field_dep_ft=field_dep_ft,
        field_dest_ft=field_dest_ft,
        cruise_alt_msl_ft=cruise_alt_msl_ft,
        actual_cruise_alt_msl_ft=actual_cruise,
        total_route_nm=total_route_nm,
        climb_ias_kt=climb_ias_kt,
        climb_rate_fpm=climb_rate_fpm,
        climb_gs_kt=climb_gs_kt,
        descent_gs_kt=descent_gs_kt,
        descent_gradient_deg=descent_gradient_deg,
        d_toc_nm=d_toc_nm,
        d_tod_nm=d_tod_nm,
        has_cruise=has_cruise,
    )


def altitude_at_distance(d_from_dep_nm: float, p: FlightProfile) -> float:
    """MSL altitude (ft) at distance `d_from_dep_nm` along the route.

    Linearly interpolates between field elev → cruise alt during climb,
    holds cruise alt between TOC and TOD, then linearly descends to
    destination field elev. Clamps to route bounds.
    """
    d = max(0.0, min(p.total_route_nm, d_from_dep_nm))
    if d <= p.d_toc_nm:
        if p.d_toc_nm <= 0:
            return p.actual_cruise_alt_msl_ft
        frac = d / p.d_toc_nm
        return p.field_dep_ft + frac * (p.actual_cruise_alt_msl_ft - p.field_dep_ft)
    if d >= p.d_tod_nm:
        descent_span = max(1e-6, p.total_route_nm - p.d_tod_nm)
        frac = (d - p.d_tod_nm) / descent_span
        return p.actual_cruise_alt_msl_ft - frac * (
            p.actual_cruise_alt_msl_ft - p.field_dest_ft)
    return p.actual_cruise_alt_msl_ft
