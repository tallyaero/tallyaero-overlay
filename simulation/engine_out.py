"""
Engine-out glide simulation module.

Position-aware state-machine simulation for emergency landing procedures.
Classifies aircraft position relative to pattern and selects appropriate strategy:
- DIRECT_FINAL: On extended final, intercept glidepath
- BASE_TO_FINAL: On base leg, turn to final
- DOWNWIND_PATTERN: Abeam/downwind, fly PO180-style pattern
- OVERHEAD_SPIRAL: Very high over field, spiral to pattern entry
- INTERCEPT_PATTERN: Random position, maneuver to pattern entry
"""
import math
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Any
from enum import Enum
from geopy import Point as GeoPoint
from geopy.distance import geodesic as geo_dist, distance

from physics import (
    compute_pressure_altitude, compute_air_density, compute_true_airspeed,
    compute_glide_ratio, adjust_glide_ratio_for_density, compute_turn_radius,
    compute_load_factor, compute_stall_speed, knots_to_fps, fps_to_knots,
    g, G_FPS2, FT_PER_NM,
    point_from, calculate_initial_compass_bearing,
    _wrap_360, _angle_diff_deg, _wind_components_from_dir,
    _cross_track_to_centerline_ft, _local_xy_ft,
)

from .base import (
    _canon_flap_config, _canon_prop_config, _get_best_glide_and_ratio
)


# === Strategy Constants ===
class Strategy(Enum):
    DIRECT_FINAL = "direct_final"
    BASE_TO_FINAL = "base_to_final"
    DOWNWIND_PATTERN = "downwind_pattern"
    OVERHEAD_SPIRAL = "overhead_spiral"
    INTERCEPT_PATTERN = "intercept_pattern"


# === Position Type Constants ===
class PositionType(Enum):
    FINAL = "final"
    BASE = "base"
    DOWNWIND = "downwind"
    ABEAM = "abeam"
    OVERHEAD = "overhead"
    OTHER = "other"


# === Altitude Status Constants ===
class AltitudeStatus(Enum):
    LOW = "low"
    ON_GLIDEPATH = "on_glidepath"
    HIGH = "high"
    VERY_HIGH = "very_high"


# === Phase Constants ===
PHASE_REACTION = "reaction"
PHASE_SPEED_TRANSITION = "speed_transition"
PHASE_TURN_TO_TARGET = "turn_to_target"
PHASE_DIRECT_APPROACH = "direct_approach"
PHASE_ALTITUDE_MGMT = "altitude_management"
PHASE_S_TURN = "s_turn"
PHASE_ORBIT = "orbit"
PHASE_SLIP = "slip"
PHASE_FINAL_INTERCEPT = "final_intercept"
PHASE_FINAL = "final"
PHASE_TOUCHDOWN = "touchdown"
PHASE_IMPACT = "impact"

# Pattern-specific phases
PHASE_DOWNWIND = "downwind"
PHASE_ABEAM = "abeam"
PHASE_BASE_TURN = "base_turn"
PHASE_BASE_LEG = "base_leg"
PHASE_SPIRAL_DESCENT = "spiral_descent"
PHASE_PATTERN_ENTRY = "pattern_entry"
PHASE_MANEUVER_TO_PATTERN = "maneuver_to_pattern"

# === Simulation Constants ===
DEFAULT_REACTION_SEC = 2.0
DEFAULT_SPEED_TAU_SEC = 4.0
DEFAULT_BANK_TAU_SEC = 1.5
DEFAULT_TIMESTEP_SEC = 0.5
MAX_SIM_TIME_SEC = 600.0

# === Position Classification Constants ===
FINAL_CORRIDOR_WIDTH_FT = 500.0
DEFAULT_PATTERN_OFFSET_FT = 3000.0  # ~0.5nm
DEFAULT_PATTERN_ALTITUDE_FT = 1000.0
BASE_LEG_NEAR_ABEAM_FT = 2000.0  # Within 2000ft of threshold along-track
BASE_LEG_MAX_CROSS_TRACK_FT = 5000.0

# === Altitude Status Thresholds ===
ALTITUDE_LOW_THRESHOLD = 0.8      # Below glidepath × this
ALTITUDE_HIGH_THRESHOLD = 1.2     # Above glidepath × this
ALTITUDE_VERY_HIGH_THRESHOLD = 2.0
OVERHEAD_MIN_ALTITUDE_FACTOR = 2.5  # Overhead if alt > pattern_alt * this

# === Heading Tolerances ===
FINAL_HEADING_TOLERANCE_DEG = 45.0
DOWNWIND_HEADING_TOLERANCE_DEG = 45.0
BASE_HEADING_TOLERANCE_DEG = 60.0

# === Approach Geometry Constants ===
FINAL_APPROACH_DIST_FT = 3000.0  # Distance from touchdown to start final
GLIDEPATH_ANGLE_DEG = 3.0  # Standard glidepath
ALTITUDE_MARGIN_FACTOR = 1.2  # Need 20% margin to "have it made"
HIGH_ALTITUDE_FACTOR = 1.5  # 50% above glidepath = too high
S_TURN_OFFSET_FT = 1500.0  # Lateral offset for S-turns

# === Capture Tolerances ===
TOUCHDOWN_XTRACK_TOL_FT = 75.0
TOUCHDOWN_HEADING_TOL_DEG = 30.0
TOUCHDOWN_ALT_RANGE_FT = (0.0, 100.0)
FINAL_INTERCEPT_ANGLE_DEG = 45.0  # Max intercept angle for final

# === Slip Constants ===
SLIP_GR_REDUCTION = 0.4  # Slip reduces glide ratio by 40%
MAX_SLIP_DURATION_SEC = 30.0

# === PO180 Turn Geometry ===
PO180_TURN_DEGREES = 180.0
BASE_TURN_DEGREES = 90.0

# === Abeam Trigger Limits ===
ABEAM_TRIGGER_MAX_XTRACK_FACTOR = 2.0
ABEAM_TRIGGER_MAX_ALONG_FT = 500.0

# === Decision Tree Safety Margin ===
# Favor Option C (full bucket progression) - the ideal flight path
# Set to 1.0 for no margin since wind model is now consistent throughout
DECISION_TREE_SAFETY_MARGIN = 1.10  # 10% — accounts for turn entry/exit losses
                                     # and wind drift during the maneuver.
                                     # Biases borderline cases to the simpler
                                     # option (Option B over C, etc.).

# === HIGH KEY (Phase EM-DYN) ===
# Entry threshold for overhead-spiral approach mode. When the aircraft has
# more than HIGH_KEY_EXCESS_FT of altitude above pattern after a wind-corrected
# direct glide to touchdown, the lateral-pattern options waste more altitude
# than an overhead spiral. Even modest excess (~300 ft) benefits from staying
# over the field — the lateral routes (Option B/C) add ~1000-1500 ft of
# extra ground track just on the half-oval + opposite spiral position.
# Number is conservative — when very tight, HIGH_KEY collapses to a near-
# straight overhead pass (no real spiral needed) and the existing simulator
# transitions cleanly into ABEAM and PO180.
HIGH_KEY_EXCESS_FT = 300.0
HIGH_KEY_BUFFER_FT = 500.0    # alt above pattern at which spiral ends


# =============================================================================
# BUCKET-BASED NAVIGATION SYSTEM
# =============================================================================

# Bucket dimension constants (all in feet or degrees)
BUCKET_TOUCHDOWN_HEIGHT = 100.0
BUCKET_TOUCHDOWN_WIDTH = 150.0
BUCKET_TOUCHDOWN_DEPTH = 200.0
BUCKET_TOUCHDOWN_HDG_TOL = 10.0

BUCKET_FINAL_HEIGHT = 300.0
BUCKET_FINAL_WIDTH = 200.0
BUCKET_FINAL_DEPTH = 500.0
BUCKET_FINAL_HDG_TOL = 15.0
BUCKET_FINAL_DIST_NM = 0.5

BUCKET_BASE_HEIGHT = 400.0
BUCKET_BASE_WIDTH = 500.0
BUCKET_BASE_DEPTH = 500.0
BUCKET_BASE_HDG_TOL = 30.0

BUCKET_ABEAM_HEIGHT = 1200.0
BUCKET_ABEAM_WIDTH = 2000.0
BUCKET_ABEAM_DEPTH = 4000.0
BUCKET_ABEAM_HDG_TOL = 90.0

BUCKET_DOWNWIND_HEIGHT = 500.0
BUCKET_DOWNWIND_WIDTH = 500.0
BUCKET_DOWNWIND_DEPTH = 1000.0
BUCKET_DOWNWIND_HDG_TOL = 30.0

BUCKET_SPIRAL_ENTRY_HEIGHT = 1000.0
BUCKET_SPIRAL_ENTRY_WIDTH = 1000.0
BUCKET_SPIRAL_ENTRY_DEPTH = 1500.0
BUCKET_SPIRAL_ENTRY_HDG_TOL = 60.0

# Final-side spiral bucket (Option B: medium altitude on final side)
BUCKET_FINAL_SPIRAL_WIDTH = 2000.0
BUCKET_FINAL_SPIRAL_DEPTH = 2000.0
BUCKET_FINAL_SPIRAL_HDG_TOL = 90.0  # Wide tolerance for spiral entry


@dataclass
class Bucket:
    """
    A 3D capture volume representing a navigation waypoint.
    Aircraft progresses through buckets: Current -> Next -> ... -> Touchdown
    """
    name: str
    lat: float
    lon: float
    altitude_ft: float

    height_ft: float
    width_ft: float
    depth_ft: float

    heading_deg: float
    heading_tol_deg: float

    next_bucket_name: Optional[str] = None

    def contains(self, lat: float, lon: float, alt_agl: float, track_deg: float, bucket_heading_ref: float) -> bool:
        """Check if position is within this bucket's capture volume."""
        dist_ft = geo_dist((lat, lon), (self.lat, self.lon)).feet

        bearing_to_pos = calculate_initial_compass_bearing(
            GeoPoint(self.lat, self.lon), GeoPoint(lat, lon)
        )
        angle_diff = math.radians(_angle_diff_deg(bearing_to_pos, bucket_heading_ref))

        along_ft = dist_ft * math.cos(angle_diff)
        cross_ft = dist_ft * math.sin(angle_diff)

        if abs(cross_ft) > self.width_ft / 2:
            return False
        if abs(along_ft) > self.depth_ft / 2:
            return False

        alt_diff = abs(alt_agl - self.altitude_ft)
        if alt_diff > self.height_ft / 2:
            return False

        hdg_diff = abs(_angle_diff_deg(track_deg, self.heading_deg))
        if hdg_diff > self.heading_tol_deg:
            return False

        return True


def _create_touchdown_bucket(
    touchdown_point: GeoPoint,
    runway_heading: float,
) -> Bucket:
    """Create the touchdown bucket starting at click point, extending down runway."""
    offset_ft = BUCKET_TOUCHDOWN_DEPTH / 2.0
    offset_nm = offset_ft / FT_PER_NM
    bucket_center = point_from(touchdown_point, runway_heading, offset_nm)

    return Bucket(
        name="TOUCHDOWN",
        lat=bucket_center.latitude,
        lon=bucket_center.longitude,
        altitude_ft=50.0,
        height_ft=BUCKET_TOUCHDOWN_HEIGHT,
        width_ft=BUCKET_TOUCHDOWN_WIDTH,
        depth_ft=BUCKET_TOUCHDOWN_DEPTH,
        heading_deg=runway_heading,
        heading_tol_deg=BUCKET_TOUCHDOWN_HDG_TOL,
        next_bucket_name=None,
    )


def _create_final_bucket(
    touchdown_point: GeoPoint,
    runway_heading: float,
    pattern_alt_ft: float,
) -> Bucket:
    """Create the final approach bucket, 0.5nm before touchdown."""
    final_dist_nm = BUCKET_FINAL_DIST_NM
    reciprocal = _wrap_360(runway_heading + 180.0)
    final_point = point_from(touchdown_point, reciprocal, final_dist_nm)

    final_dist_ft = final_dist_nm * FT_PER_NM
    final_alt = final_dist_ft * math.tan(math.radians(GLIDEPATH_ANGLE_DEG))

    return Bucket(
        name="FINAL",
        lat=final_point.latitude,
        lon=final_point.longitude,
        altitude_ft=final_alt,
        height_ft=BUCKET_FINAL_HEIGHT,
        width_ft=BUCKET_FINAL_WIDTH,
        depth_ft=BUCKET_FINAL_DEPTH,
        heading_deg=runway_heading,
        heading_tol_deg=BUCKET_FINAL_HDG_TOL,
        next_bucket_name="TOUCHDOWN",
    )


def _create_base_bucket(
    touchdown_point: GeoPoint,
    runway_heading: float,
    pattern_offset_ft: float,
    pattern_alt_ft: float,
    pattern_side: str,
) -> Bucket:
    """Create the base leg bucket, perpendicular to runway at pattern offset."""
    if pattern_side == "left":
        base_bearing = _wrap_360(runway_heading - 90.0)
        base_heading = _wrap_360(runway_heading + 90.0)
    else:
        base_bearing = _wrap_360(runway_heading + 90.0)
        base_heading = _wrap_360(runway_heading - 90.0)

    base_point = point_from(touchdown_point, base_bearing, pattern_offset_ft / FT_PER_NM)
    base_alt = pattern_alt_ft * 0.7

    return Bucket(
        name="BASE",
        lat=base_point.latitude,
        lon=base_point.longitude,
        altitude_ft=base_alt,
        height_ft=BUCKET_BASE_HEIGHT,
        width_ft=BUCKET_BASE_WIDTH,
        depth_ft=BUCKET_BASE_DEPTH,
        heading_deg=base_heading,
        heading_tol_deg=BUCKET_BASE_HDG_TOL,
        next_bucket_name="FINAL",
    )


def _create_abeam_bucket(
    touchdown_point: GeoPoint,
    runway_heading: float,
    pattern_offset_ft: float,
    pattern_alt_ft: float,
    pattern_side: str,
) -> Bucket:
    """Create the abeam bucket, opposite runway at pattern offset."""
    if pattern_side == "left":
        abeam_bearing = _wrap_360(runway_heading - 90.0)
    else:
        abeam_bearing = _wrap_360(runway_heading + 90.0)

    abeam_point = point_from(touchdown_point, abeam_bearing, pattern_offset_ft / FT_PER_NM)
    downwind_heading = _wrap_360(runway_heading + 180.0)

    return Bucket(
        name="ABEAM",
        lat=abeam_point.latitude,
        lon=abeam_point.longitude,
        altitude_ft=pattern_alt_ft,
        height_ft=BUCKET_ABEAM_HEIGHT,
        width_ft=BUCKET_ABEAM_WIDTH,
        depth_ft=BUCKET_ABEAM_DEPTH,
        heading_deg=downwind_heading,
        heading_tol_deg=BUCKET_ABEAM_HDG_TOL,
        next_bucket_name="BASE",
    )


def _create_downwind_bucket(
    touchdown_point: GeoPoint,
    runway_heading: float,
    pattern_offset_ft: float,
    pattern_alt_ft: float,
    pattern_side: str,
) -> Bucket:
    """Create the downwind bucket, upwind of abeam at pattern offset."""
    if pattern_side == "left":
        lateral_bearing = _wrap_360(runway_heading - 90.0)
    else:
        lateral_bearing = _wrap_360(runway_heading + 90.0)

    behind_dist_nm = 0.5
    reciprocal = _wrap_360(runway_heading + 180.0)
    behind_point = point_from(touchdown_point, reciprocal, behind_dist_nm)
    downwind_point = point_from(behind_point, lateral_bearing, pattern_offset_ft / FT_PER_NM)
    downwind_heading = _wrap_360(runway_heading + 180.0)

    return Bucket(
        name="DOWNWIND",
        lat=downwind_point.latitude,
        lon=downwind_point.longitude,
        altitude_ft=pattern_alt_ft,
        height_ft=BUCKET_DOWNWIND_HEIGHT,
        width_ft=BUCKET_DOWNWIND_WIDTH,
        depth_ft=BUCKET_DOWNWIND_DEPTH,
        heading_deg=downwind_heading,
        heading_tol_deg=BUCKET_DOWNWIND_HDG_TOL,
        next_bucket_name="ABEAM",
    )


def _create_spiral_entry_bucket(
    aircraft_pos: GeoPoint,
    aircraft_alt: float,
    touchdown_point: GeoPoint,
    pattern_offset_ft: float,
    pattern_side: str,
) -> Bucket:
    """Create a dynamic spiral entry bucket positioned BETWEEN aircraft and touchdown."""
    dist_to_aircraft_ft = geo_dist(
        (touchdown_point.latitude, touchdown_point.longitude),
        (aircraft_pos.latitude, aircraft_pos.longitude)
    ).feet

    bearing_to_aircraft = calculate_initial_compass_bearing(touchdown_point, aircraft_pos)

    min_dist = pattern_offset_ft
    max_dist = dist_to_aircraft_ft * 0.5
    bucket_dist_ft = max(min_dist, min(max_dist, dist_to_aircraft_ft * 0.33))

    spiral_entry_point = point_from(touchdown_point, bearing_to_aircraft, bucket_dist_ft / FT_PER_NM)
    heading_toward_td = _wrap_360(bearing_to_aircraft + 180.0)

    return Bucket(
        name="SPIRAL_ENTRY",
        lat=spiral_entry_point.latitude,
        lon=spiral_entry_point.longitude,
        altitude_ft=aircraft_alt - 300,
        height_ft=BUCKET_SPIRAL_ENTRY_HEIGHT,
        width_ft=BUCKET_SPIRAL_ENTRY_WIDTH,
        depth_ft=BUCKET_SPIRAL_ENTRY_DEPTH,
        heading_deg=heading_toward_td,
        heading_tol_deg=BUCKET_SPIRAL_ENTRY_HDG_TOL,
        next_bucket_name="SPIRAL_DESCENT",
    )


def _create_opposite_spiral_bucket(
    abeam_bucket: Bucket,
    touchdown_point: GeoPoint,
    runway_heading: float,
    pattern_offset_ft: float,
    pattern_side: str,
) -> Bucket:
    """
    Create an OPPOSITE_SPIRAL bucket on the opposite side of the runway from ABEAM.

    This is used when the aircraft starts on the opposite side of the runway from
    the pattern. The aircraft will spiral down in the OPPOSITE_SPIRAL bucket, then
    do a half-spiral (~180°) to cross the runway and arrive at ABEAM.

    The bucket is positioned at the same offset distance from the runway centerline
    as ABEAM, but on the opposite side.
    """
    # Opposite side bearing (mirror of ABEAM position)
    if pattern_side == "left":
        # ABEAM is on left, so opposite is on right
        opposite_bearing = _wrap_360(runway_heading + 90.0)
    else:
        # ABEAM is on right, so opposite is on left
        opposite_bearing = _wrap_360(runway_heading - 90.0)

    # Position at same offset distance from touchdown, but on opposite side
    opposite_point = point_from(touchdown_point, opposite_bearing, pattern_offset_ft / FT_PER_NM)

    # Heading should face OPPOSITE direction from normal SPIRAL
    # Normal SPIRAL faces downwind (runway_heading + 180)
    # OPPOSITE_SPIRAL faces upwind/toward runway (runway_heading)
    # This allows aircraft coming from the final side to enter the bucket
    bucket_heading = runway_heading  # Opposite of downwind

    # Use same altitude range as regular spiral (high ceiling for capture)
    spiral_lower = abeam_bucket.altitude_ft + abeam_bucket.height_ft / 2 + 1000
    spiral_upper = 15000.0
    spiral_center = (spiral_lower + spiral_upper) / 2.0
    spiral_height = spiral_upper - spiral_lower

    return Bucket(
        name="OPPOSITE_SPIRAL",
        lat=opposite_point.latitude,
        lon=opposite_point.longitude,
        altitude_ft=spiral_center,
        height_ft=spiral_height,
        width_ft=2000.0,
        depth_ft=2000.0,
        heading_deg=bucket_heading,
        heading_tol_deg=90.0,  # Wide tolerance since we're approaching from various angles
        next_bucket_name="ABEAM",
    )


def _create_final_spiral_bucket(
    start_pos: GeoPoint,
    start_alt: float,
    touchdown_point: GeoPoint,
    runway_heading: float,
    final_bucket: 'Bucket',
    glide_ratio: float,
) -> Bucket:
    """
    Create a FINAL_SPIRAL bucket on the extended final approach path.

    This is used when the aircraft starts on the final side with medium altitude:
    - Too high for straight-to-final (Option A)
    - But NOT enough altitude to justify full OPPOSITE_SPIRAL → ABEAM → PO180 flow (Option C)

    The spiral is positioned on extended final and sized based on altitude to lose.
    Aircraft spirals down until reaching an altitude where straight-in to FINAL is possible.

    The bucket is positioned between the start position and final bucket,
    along the extended centerline.
    """
    # Position the spiral bucket near the extended final centerline.
    # The old version offset the bucket by up to ±2000 ft based on the
    # aircraft's current cross-track, which left it well off-CL and
    # forced an S-shaped transit across the runway after spiral exit.
    # Tighten the cap to ±500 ft so the spiral is nearly on-CL — the
    # aircraft does a short transit from its current xtrack toward the
    # bucket, spirals there, then exits roughly aligned with final.
    # The small remaining offset lets far-off-CL starts still reach the
    # bucket within their glide budget.
    xtrack_ft, _along_ft = _cross_track_to_centerline_ft(
        touchdown_point, start_pos, runway_heading
    )
    lateral_offset = max(-500.0, min(500.0, xtrack_ft))

    final_point = GeoPoint(final_bucket.lat, final_bucket.lon)
    dist_start_to_final = geo_dist(
        (start_pos.latitude, start_pos.longitude),
        (final_point.latitude, final_point.longitude)
    ).feet

    # Place bucket 2/3 of the way from FINAL toward start.
    spiral_dist_from_final = dist_start_to_final * 0.67
    spiral_dist_from_final = max(2000.0, min(spiral_dist_from_final, 15000.0))

    # Position on extended final, then apply the (small) lateral nudge.
    reciprocal = _wrap_360(runway_heading + 180.0)
    spiral_center = point_from(final_point, reciprocal, spiral_dist_from_final / FT_PER_NM)
    if abs(lateral_offset) > 50:
        lateral_bearing = (_wrap_360(runway_heading + 90.0) if lateral_offset > 0
                           else _wrap_360(runway_heading - 90.0))
        spiral_center = point_from(
            spiral_center, lateral_bearing, abs(lateral_offset) / FT_PER_NM)

    # Calculate altitude for the bucket center
    # The bucket should capture the aircraft at its current altitude
    # and have a wide altitude range since we're spiraling down
    final_approach_alt = final_bucket.altitude_ft + final_bucket.height_ft / 2
    spiral_lower = final_approach_alt + 500  # Bottom of capture range
    spiral_upper = start_alt + 500  # Top of capture range (above current alt)
    spiral_center_alt = (spiral_lower + spiral_upper) / 2.0
    spiral_height = spiral_upper - spiral_lower

    # Entry heading: facing touchdown (runway heading) allows approach from final side
    bucket_heading = runway_heading

    return Bucket(
        name="FINAL_SPIRAL",
        lat=spiral_center.latitude,
        lon=spiral_center.longitude,
        altitude_ft=spiral_center_alt,
        height_ft=spiral_height,
        width_ft=BUCKET_FINAL_SPIRAL_WIDTH,
        depth_ft=BUCKET_FINAL_SPIRAL_DEPTH,
        heading_deg=bucket_heading,
        heading_tol_deg=BUCKET_FINAL_SPIRAL_HDG_TOL,
        next_bucket_name="FINAL",
    )


def _can_reach_bucket(
    current_pos: GeoPoint,
    current_alt: float,
    target_bucket: Bucket,
    glide_ratio: float,
    safety_margin: float = 1.1,
) -> bool:
    """Check if we can glide from current position to target bucket."""
    dist_ft = geo_dist(
        (current_pos.latitude, current_pos.longitude),
        (target_bucket.lat, target_bucket.lon)
    ).feet

    alt_to_lose = current_alt - target_bucket.altitude_ft
    if alt_to_lose <= 0:
        return dist_ft < target_bucket.depth_ft

    required_gr = dist_ft / alt_to_lose
    return required_gr <= (glide_ratio / safety_margin)


def _can_arrive_at_bucket_altitude(
    current_pos: GeoPoint,
    current_alt: float,
    target_bucket: Bucket,
    glide_ratio: float,
    tolerance_ft: float = 500.0,
    tas_kt: float = 75.0,
    wind_dir: float = 0.0,
    wind_speed_kt: float = 0.0,
) -> bool:
    """Check if we'd arrive at the bucket at approximately the correct altitude."""
    dist_ft = geo_dist(
        (current_pos.latitude, current_pos.longitude),
        (target_bucket.lat, target_bucket.lon)
    ).feet

    # Wind-correct distance for consistent ground track model
    bearing_to_bucket = calculate_initial_compass_bearing(
        current_pos, GeoPoint(target_bucket.lat, target_bucket.lon)
    )
    dist_ft_wc = _wind_corrected_glide_distance(
        dist_ft, bearing_to_bucket, tas_kt, wind_dir, wind_speed_kt
    )

    alt_at_arrival = current_alt - (dist_ft_wc / glide_ratio)
    alt_diff = abs(alt_at_arrival - target_bucket.altitude_ft)

    return alt_diff <= tolerance_ft


def _calculate_slip_for_bucket(
    current_alt: float,
    dist_to_bucket_ft: float,
    target_bucket_alt: float,
    glide_ratio: float,
) -> Tuple[float, float]:
    """Calculate slip intensity needed to reach target bucket."""
    alt_to_lose = current_alt - target_bucket_alt
    if alt_to_lose <= 0 or dist_to_bucket_ft <= 0:
        return 0.0, glide_ratio

    required_gr = dist_to_bucket_ft / alt_to_lose

    if required_gr >= glide_ratio:
        return 0.0, glide_ratio

    min_slip_gr = glide_ratio * (1.0 - SLIP_GR_REDUCTION)
    min_slip_gr = max(3.0, min_slip_gr)

    if required_gr <= min_slip_gr:
        return 1.0, min_slip_gr

    gr_range = glide_ratio - min_slip_gr
    gr_reduction_needed = glide_ratio - required_gr
    slip_intensity = gr_reduction_needed / gr_range if gr_range > 0 else 0.0
    slip_intensity = max(0.0, min(1.0, slip_intensity))

    effective_gr = glide_ratio * (1.0 - slip_intensity * SLIP_GR_REDUCTION)
    return slip_intensity, effective_gr


def _wind_corrected_glide_distance(
    geometric_dist_ft: float,
    track_deg: float,
    tas_kt: float,
    wind_dir: float,
    wind_speed_kt: float,
) -> float:
    """
    Calculate the effective glide distance accounting for wind using proper wind triangle.

    Returns the distance that consumes the same altitude as the geometric
    distance would in still air, but accounting for actual ground speed.

    Uses the same wind triangle calculation as the simulation to ensure consistency:
    - Aircraft crabs into crosswind to maintain track
    - Ground speed accounts for both headwind component AND crab angle effect

    For headwind: GS < TAS → ratio > 1 → effective distance LONGER (more altitude needed)
    For tailwind: GS > TAS → ratio < 1 → effective distance SHORTER (less altitude needed)

    Args:
        geometric_dist_ft: The pure geometric distance in feet
        track_deg: Direction of flight for this segment (degrees true)
        tas_kt: True airspeed in knots
        wind_dir: Wind FROM direction (degrees true)
        wind_speed_kt: Wind speed in knots
    """
    if wind_speed_kt < 0.5:
        return geometric_dist_ft

    # Wind components (fps) - same as simulation
    wn_fps, we_fps = _wind_components_from_dir(wind_dir, wind_speed_kt)
    tas_fps = tas_kt * 1.68781  # knots to fps

    # Solve wind triangle - MUST match _compute_wind_correction_angle exactly
    track_rad = math.radians(_wrap_360(track_deg))

    # Crosswind component (perpendicular to track)
    w_cross = (-wn_fps * math.sin(track_rad)) + (we_fps * math.cos(track_rad))
    # Headwind component (along track, positive = headwind)
    w_head = (wn_fps * math.cos(track_rad)) + (we_fps * math.sin(track_rad))

    # Wind correction angle (crab angle)
    if tas_fps > 1.0:
        wca_ratio = max(-1.0, min(1.0, w_cross / tas_fps))
        wca_rad = math.asin(wca_ratio)
    else:
        wca_rad = 0.0

    # Ground speed using proper wind triangle
    # TAS component along track is reduced by cos(wca) due to crabbing
    gs_fps = tas_fps * math.cos(wca_rad) + w_head
    gs_fps = max(1.0, gs_fps)

    # Effective distance = geometric × (TAS/GS)
    # Headwind: GS < TAS → ratio > 1 → effective distance LONGER
    # Tailwind: GS > TAS → ratio < 1 → effective distance SHORTER
    if gs_fps > 10:
        return geometric_dist_ft * (tas_fps / gs_fps)
    else:
        # Strong headwind - cap at 2x distance for safety
        return geometric_dist_ft * 2.0


# =============================================================================
# Dynamic geometry helpers (Phase EM-DYN)
# =============================================================================

def _dynamic_pattern_offset_ft(tas_kt: float, max_bank_deg: float) -> float:
    """Lateral pattern spacing sized so the PO180 turn from abeam ends
    directly on the runway centerline at the touchdown point — i.e.,
    no straight final leg, continuous turn base→final.

    Geometry: a 180° turn at constant bank moves the aircraft laterally
    by 2R (turn diameter). If pattern_offset = 2R, the aircraft starting
    perpendicular to the runway at pattern_offset distance and turning
    180° will end up on centerline at the touchdown's along-track
    position. +20% margin to absorb roll-in / roll-out time + wind drift.

    For engine-out at 76 kt TAS with 45° max bank, this yields ~1130 ft
    — a tight pattern, which is what an instructor would teach for
    a power-off approach (you stay close so you don't lose the field)."""
    tas_fps = max(1.0, tas_kt * 1.68781)
    R = _calculate_turn_radius_for_bank(tas_fps, max_bank_deg)
    if R == float('inf'):
        return DEFAULT_PATTERN_OFFSET_FT
    return max(800.0, min(3500.0, R * 2.2))


# =============================================================================
# Energy-budget helpers (Phase EM-DYN)
# =============================================================================
# Replace hard-coded thresholds with formulas keyed off the aircraft's actual
# energy state. The fundamental variable is "altitude excess" — how much
# altitude is left over after gliding direct-line to the touchdown point and
# arriving at pattern altitude. Every gate in _build_bucket_chain is derived
# from this number so the decision tree responds the way a real pilot would
# (cautious when tight, generous when fat).

@dataclass
class _EnergyBudget:
    direct_dist_ft: float            # straight-line ground distance start → touchdown
    wind_corrected_dist_ft: float    # wind-adjusted equivalent distance
    direct_glide_alt_ft: float       # altitude burned flying direct
    alt_at_field_agl: float          # altitude AGL upon arrival overhead touchdown
    alt_excess_ft: float             # alt_at_field_agl − pattern_alt_ft (master variable)


def _compute_energy_budget(start_pos: GeoPoint,
                             start_alt_agl: float,
                             touchdown_point: GeoPoint,
                             pattern_alt_ft: float,
                             glide_ratio: float,
                             tas_kt: float,
                             wind_dir: float,
                             wind_speed_kt: float) -> _EnergyBudget:
    """Master energy-state calculation. All bucket-chain gates derive from this."""
    direct_dist_ft = geo_dist(
        (start_pos.latitude, start_pos.longitude),
        (touchdown_point.latitude, touchdown_point.longitude)
    ).feet
    track = calculate_initial_compass_bearing(start_pos, touchdown_point)
    wc_dist = _wind_corrected_glide_distance(
        direct_dist_ft, track, tas_kt, wind_dir, wind_speed_kt)
    glide_alt = wc_dist / glide_ratio
    arrival = max(0.0, start_alt_agl - glide_alt)
    excess = arrival - pattern_alt_ft
    return _EnergyBudget(
        direct_dist_ft=direct_dist_ft,
        wind_corrected_dist_ft=wc_dist,
        direct_glide_alt_ft=glide_alt,
        alt_at_field_agl=arrival,
        alt_excess_ft=excess,
    )


def _curving_join_alt_cost_ft(xtrack_ft: float,
                                heading_diff_deg: float,
                                tas_kt: float,
                                glide_ratio: float,
                                max_bank_deg: float = 30.0) -> float:
    """Approximate altitude consumed when joining the runway centerline from
    a position with given cross-track + heading difference.

    Decomposed into two terms:
      arc_alt:    cost of swinging through heading_diff_deg at turn radius R
                  → (R × Δψ_rad) / GR
      xtrack_alt: extra ground distance pulled in laterally by ~xtrack/2
                  → (|xtrack| × 0.5) / GR
    Both are pessimistic — the actual curving arc length is somewhere
    between the two extremes — so the sum is a conservative upper bound.

    Returns ft of altitude consumed by the curving join (always >= 0)."""
    tas_fps = max(1.0, tas_kt * 1.68781)
    R = _calculate_turn_radius_for_bank(tas_fps, max_bank_deg)
    if R == float('inf'):
        return float('inf')
    arc_alt = (R * math.radians(max(0.0, heading_diff_deg))) / max(1.0, glide_ratio)
    xtrack_alt = (abs(xtrack_ft) * 0.5) / max(1.0, glide_ratio)
    return arc_alt + xtrack_alt


def _curving_join_viable(xtrack_ft: float,
                          heading_diff_deg: float,
                          tas_kt: float,
                          glide_ratio: float,
                          alt_excess_at_target_ft: float,
                          max_bank_deg: float = 30.0,
                          alt_buffer_ft: float = 50.0) -> bool:
    """Combined geometric + energy gate for the curving join (Option A).

    Geometric: a single-turn capture of centerline is only possible when
    |xtrack| ≤ 2R. Beyond that, an s-turn or pattern is required.

    Energy: the curving cost must fit within alt_excess_at_target_ft + buffer."""
    tas_fps = max(1.0, tas_kt * 1.68781)
    R = _calculate_turn_radius_for_bank(tas_fps, max_bank_deg)
    if R == float('inf'):
        return False
    if abs(xtrack_ft) > 2.0 * R:
        return False
    cost = _curving_join_alt_cost_ft(xtrack_ft, heading_diff_deg, tas_kt,
                                       glide_ratio, max_bank_deg)
    return alt_excess_at_target_ft >= cost + alt_buffer_ft


def _build_bucket_chain(
    start_pos: GeoPoint,
    start_alt: float,
    start_heading: float,
    touchdown_point: GeoPoint,
    runway_heading: float,
    pattern_offset_ft: float,
    pattern_alt_ft: float,
    glide_ratio: float,
    force_pattern_side: Optional[str] = None,
    wind_dir: float = 0.0,
    wind_speed_kt: float = 0.0,
    tas_kt: float = 75.0,
    max_bank_deg: float = 30.0,
) -> Tuple[List[Bucket], str, bool]:
    """
    Build the optimal bucket chain based on starting position.

    The perpendicular line through touchdown point (perpendicular to runway heading)
    divides space into:
    - UPWIND side (along_track >= 0): Behind touchdown, where pattern is flown
    - FINAL side (along_track < 0): In front of touchdown, where final approach comes from

    FINAL SIDE has three options (A/B/C):
    - Option A: Straight to Final - low altitude, aligned, near centerline
    - Option B: Final-Side Spiral - medium altitude, stay on final side
    - Option C: Full Opposite Spiral Flow - high altitude, full pattern needed

    UPWIND SIDE uses normal SPIRAL (above ABEAM).

    Args:
        force_pattern_side: If provided ("left" or "right"), forces the pattern to that side.

    Returns:
        (bucket_chain, pattern_side, use_opposite_spiral)
    """
    # Dynamic pattern offset — sized to enable continuous turn base→final
    # from the abeam position. Replaces the legacy DEFAULT_PATTERN_OFFSET_FT
    # (3000 ft) with a turn-diameter-derived value so the 180° PO180 turn
    # ends directly on the runway with no straight final segment. Pilots
    # flying engine-out keep tight patterns; the simulator should too.
    pattern_offset_ft = _dynamic_pattern_offset_ft(tas_kt, max_bank_deg)

    xtrack_ft, along_ft = _cross_track_to_centerline_ft(
        touchdown_point, start_pos, runway_heading
    )

    # Determine which cross-track side the start position is on
    start_cross_side = "left" if xtrack_ft < 0 else "right"

    # Determine if start is on FINAL side (in front of touchdown) or UPWIND side (behind touchdown)
    # The perpendicular line through touchdown is the dividing line
    on_final_side = along_ft < 0

    # ABEAM is ALWAYS on the SAME cross-track side as the start position
    if force_pattern_side is not None:
        pattern_side = force_pattern_side
    else:
        pattern_side = start_cross_side

    touchdown_bucket = _create_touchdown_bucket(touchdown_point, runway_heading)
    final_bucket = _create_final_bucket(touchdown_point, runway_heading, pattern_alt_ft)
    base_bucket = _create_base_bucket(touchdown_point, runway_heading, pattern_offset_ft, pattern_alt_ft, pattern_side)
    abeam_bucket = _create_abeam_bucket(touchdown_point, runway_heading, pattern_offset_ft, pattern_alt_ft, pattern_side)
    downwind_bucket = _create_downwind_bucket(touchdown_point, runway_heading, pattern_offset_ft, pattern_alt_ft, pattern_side)

    heading_diff = abs(_angle_diff_deg(start_heading, runway_heading))

    # Energy budget — the master variable. Every gate below derives from this.
    energy = _compute_energy_budget(
        start_pos, start_alt, touchdown_point,
        pattern_alt_ft, glide_ratio, tas_kt, wind_dir, wind_speed_kt,
    )

    # =========================================================================
    # HIGH KEY (Phase EM-DYN) — overhead-spiral approach mode.
    #
    # Applies ONLY to FINAL-SIDE starts (aircraft in front of touchdown along
    # the runway extended centerline). For those quadrants, when the
    # aircraft has more altitude than needed to fly direct AND complete the
    # pattern, the right play is "fly direct, spiral overhead, then PO180" —
    # not a lateral pattern.
    #
    # UPWIND-SIDE starts (behind touchdown) take a different route: fly to
    # the same-side abeam point, spiral there, then PO180 base→final. That
    # logic lives in the upwind-side branch further down and was already
    # correct — gating HIGH_KEY here keeps us from short-circuiting it.
    #
    # The HIGH_KEY bucket is a SPIRAL bucket positioned over the touchdown
    # point (same lat/lon, not the perpendicular abeam offset). The
    # simulator's existing SPIRAL phase logic with active orbit guidance
    # (Phase EM-DYN orbit-center pursuit) orbits at the bucket's lat/lon
    # and descends through the bucket's altitude band.
    # =========================================================================
    if on_final_side and energy.alt_excess_ft > HIGH_KEY_EXCESS_FT:
        # High-key altitude band: bottom is the low-key handoff (pattern_alt +
        # 500 ft); top is intentionally far above any plausible approach
        # altitude so the aircraft is *always* inside the band the moment it
        # crosses overhead. The simulator's spiral-entry check requires
        # contains() to be True; a tight altitude band caused the previous
        # iteration to miss aircraft that arrived slightly above the
        # computed top, and they then just flew past the field. Mirrors the
        # 15000 ft cap used by the existing UPWIND SPIRAL bucket so behavior
        # is consistent.
        high_key_bottom = pattern_alt_ft + HIGH_KEY_BUFFER_FT
        high_key_top = 15000.0
        high_key_center = (high_key_top + high_key_bottom) / 2.0
        high_key_height = high_key_top - high_key_bottom
        high_key_bucket = Bucket(
            name="SPIRAL",  # reuse existing simulator phase logic
            lat=touchdown_point.latitude,
            lon=touchdown_point.longitude,
            altitude_ft=high_key_center,
            height_ft=high_key_height,
            # Tight capture so the aircraft has to be near touchdown
            # before the spiral phase activates. With a wide capture
            # (3000 ft) the aircraft would start banking at the bucket
            # edge, putting the orbit center ~1500 ft + R off the
            # touchdown point. 1500 ft bucket keeps the entry inside
            # 750 ft of center; active orbit guidance pulls the rest.
            width_ft=1500.0,
            depth_ft=1500.0,
            heading_deg=runway_heading,
            heading_tol_deg=180.0,  # any heading is OK over the field
            next_bucket_name="ABEAM",
        )
        return [high_key_bucket, abeam_bucket, touchdown_bucket], pattern_side, False

    # =========================================================================
    # FINAL SIDE DECISION TREE (Options A, B, C)
    # =========================================================================
    if on_final_side:
        # Option A: Straight-in with curving join.
        # Replaces the legacy rigid "aligned AND xtrack < 1500" gate with an
        # energy-derived viability check. The curving join is taken when:
        #   - the aircraft can physically reach the FINAL bucket with margin
        #   - the curving join cost (arc through heading_diff + lateral pull-in
        #     by xtrack) fits inside the altitude excess we have at the FINAL
        #     bucket
        #   - the cross-track can be captured in a single turn (|xtrack| ≤ 2R)
        # This both ACCEPTS far-but-fat approaches (e.g. 2500 ft xtrack with
        # 1500 ft of excess) and REJECTS close-but-thin ones (e.g. 800 ft
        # xtrack with only 50 ft excess) that the old gate got wrong.
        if _can_arrive_at_bucket_altitude(start_pos, start_alt, final_bucket, glide_ratio, 300,
                                          tas_kt, wind_dir, wind_speed_kt):
            # Excess altitude at the final-bucket arrival point.
            alt_excess_at_final = (
                start_alt
                - energy.direct_glide_alt_ft
                - final_bucket.altitude_ft
            )
            if _curving_join_viable(xtrack_ft, heading_diff, tas_kt,
                                     glide_ratio, alt_excess_at_final,
                                     max_bank_deg=max_bank_deg):
                return [final_bucket, touchdown_bucket], pattern_side, False

        # =======================================================================
        # DECISION: Option B (final-side spiral) vs Option C (opposite spiral)
        #
        # The cutoff is the MINIMUM ALTITUDE required to complete Option C.
        # If below that minimum → Option B (can't complete full pattern)
        # If at or above that minimum → Option C (use full pattern distance)
        # =======================================================================

        # Calculate Option C minimum altitude requirement
        # Ground track: start → OPPOSITE_SPIRAL → half-oval to ABEAM → PO180 → touchdown

        # Distance from start to OPPOSITE_SPIRAL bucket position (opposite side of runway)
        if pattern_side == "left":
            opposite_bearing = _wrap_360(runway_heading + 90.0)  # ABEAM on left, opposite on right
        else:
            opposite_bearing = _wrap_360(runway_heading - 90.0)  # ABEAM on right, opposite on left

        opposite_spiral_pos = point_from(touchdown_point, opposite_bearing, pattern_offset_ft / FT_PER_NM)
        dist_start_to_opposite_spiral = geo_dist(
            (start_pos.latitude, start_pos.longitude),
            (opposite_spiral_pos.latitude, opposite_spiral_pos.longitude)
        ).feet

        # Half-oval arc from OPPOSITE_SPIRAL to ABEAM (180° turn crossing the runway)
        # The turn diameter spans from one side of runway to the other = 2 × pattern_offset
        half_oval_radius = pattern_offset_ft
        half_oval_arc = math.pi * half_oval_radius

        # PO180 pattern from ABEAM: downwind leg + 180° turn + final approach
        po180_turn_radius = pattern_offset_ft / 2.0
        po180_turn_arc = math.pi * po180_turn_radius
        po180_downwind_leg = pattern_offset_ft * 0.5  # Downwind travel before turn starts
        po180_final_leg = BUCKET_FINAL_DIST_NM * FT_PER_NM  # Distance from FINAL bucket to touchdown

        # ===================================================================
        # WIND-CORRECTED DISTANCE CALCULATIONS
        # Apply wind correction to each leg to get effective glide distances
        # ===================================================================

        # Leg 1: Start to OPPOSITE_SPIRAL
        # Track direction: bearing from start to opposite spiral position
        track_1 = calculate_initial_compass_bearing(start_pos, opposite_spiral_pos)
        dist_1_corrected = _wind_corrected_glide_distance(
            dist_start_to_opposite_spiral, track_1, tas_kt, wind_dir, wind_speed_kt
        )

        # Leg 2: Half-oval arc from OPPOSITE_SPIRAL to ABEAM
        # Average track is roughly perpendicular to runway (crossing pattern)
        if pattern_side == "left":
            track_2_avg = _wrap_360(runway_heading - 90.0)  # Crossing right to left
        else:
            track_2_avg = _wrap_360(runway_heading + 90.0)  # Crossing left to right
        dist_2_corrected = _wind_corrected_glide_distance(
            half_oval_arc, track_2_avg, tas_kt, wind_dir, wind_speed_kt
        )

        # Leg 3: Downwind leg from ABEAM (opposite runway heading - tailwind typically)
        track_3_downwind = _wrap_360(runway_heading + 180.0)
        dist_3_corrected = _wind_corrected_glide_distance(
            po180_downwind_leg, track_3_downwind, tas_kt, wind_dir, wind_speed_kt
        )

        # Leg 4: PO180 turn arc (downwind through base turn)
        # Average track through 180° turn - use perpendicular as approximation
        if pattern_side == "left":
            track_4_avg = _wrap_360(runway_heading + 90.0)  # Left pattern base turn
        else:
            track_4_avg = _wrap_360(runway_heading - 90.0)  # Right pattern base turn
        dist_4_corrected = _wind_corrected_glide_distance(
            po180_turn_arc, track_4_avg, tas_kt, wind_dir, wind_speed_kt
        )

        # Leg 5: Final approach (aligned with runway heading - typically into wind)
        track_5 = runway_heading
        dist_5_corrected = _wind_corrected_glide_distance(
            po180_final_leg, track_5, tas_kt, wind_dir, wind_speed_kt
        )

        # Total Option C ground track with wind correction
        option_c_ground_track = (dist_1_corrected + dist_2_corrected + dist_3_corrected +
                                 dist_4_corrected + dist_5_corrected)

        # Minimum altitude to complete Option C (must have enough glide distance)
        # Add ABEAM bucket altitude as the target arrival altitude at ABEAM
        # Apply safety margin to account for turn inefficiencies and wind variations
        abeam_target_alt = abeam_bucket.altitude_ft
        option_c_min_altitude = ((option_c_ground_track / glide_ratio) * DECISION_TREE_SAFETY_MARGIN
                                 + abeam_target_alt)

        # =======================================================================
        # DECISION
        # =======================================================================
        # If start_alt >= option_c_min_altitude → Option C (full pattern)
        # If start_alt < option_c_min_altitude → Option B (final-side spiral)
        # =======================================================================

        if start_alt >= option_c_min_altitude:
            # Option C: Full Opposite Spiral Flow
            # Aircraft has enough altitude to complete the full pattern
            # Path: OPPOSITE_SPIRAL → half-oval → ABEAM → PO180 → TOUCHDOWN
            opposite_spiral_bucket = _create_opposite_spiral_bucket(
                abeam_bucket, touchdown_point, runway_heading, pattern_offset_ft, pattern_side
            )
            return [opposite_spiral_bucket, abeam_bucket, touchdown_bucket], pattern_side, True
        else:
            # Option B: Final-Side Spiral
            # Not enough altitude for full pattern - stay on final side
            # Spiral down until altitude allows straight approach to FINAL
            final_spiral_bucket = _create_final_spiral_bucket(
                start_pos, start_alt, touchdown_point, runway_heading, final_bucket, glide_ratio
            )
            return [final_spiral_bucket, final_bucket, touchdown_bucket], pattern_side, False

    # =========================================================================
    # UPWIND SIDE: Two options based on altitude
    # - High altitude: SPIRAL → ABEAM → PO180 → TOUCHDOWN
    # - Low altitude: ABEAM → PO180 → TOUCHDOWN (skip spiral)
    #
    # Decision based on minimum altitude required for full SPIRAL flow
    # =========================================================================
    else:
        # Option A check on the upwind side — energy-derived gate (same as
        # final-side branch above).
        if _can_arrive_at_bucket_altitude(start_pos, start_alt, final_bucket, glide_ratio, 300,
                                          tas_kt, wind_dir, wind_speed_kt):
            alt_excess_at_final = (
                start_alt
                - energy.direct_glide_alt_ft
                - final_bucket.altitude_ft
            )
            if _curving_join_viable(xtrack_ft, heading_diff, tas_kt,
                                     glide_ratio, alt_excess_at_final,
                                     max_bank_deg=max_bank_deg):
                return [final_bucket, touchdown_bucket], pattern_side, False

        # =======================================================================
        # Calculate minimum altitude for SPIRAL → ABEAM → PO180 → TOUCHDOWN
        # =======================================================================

        # Distance from start to ABEAM/SPIRAL position
        dist_start_to_abeam = geo_dist(
            (start_pos.latitude, start_pos.longitude),
            (abeam_bucket.lat, abeam_bucket.lon)
        ).feet

        # PO180 pattern from ABEAM: downwind leg + 180° turn + final approach
        po180_turn_radius = pattern_offset_ft / 2.0
        po180_turn_arc = math.pi * po180_turn_radius
        po180_downwind_leg = pattern_offset_ft * 0.5  # Downwind travel before turn starts
        po180_final_leg = BUCKET_FINAL_DIST_NM * FT_PER_NM

        # ===================================================================
        # WIND-CORRECTED DISTANCE CALCULATIONS
        # Apply wind correction to each leg to get effective glide distances
        # ===================================================================

        # Leg 1: Start to ABEAM/SPIRAL position
        abeam_point = GeoPoint(abeam_bucket.lat, abeam_bucket.lon)
        track_1 = calculate_initial_compass_bearing(start_pos, abeam_point)
        dist_1_corrected = _wind_corrected_glide_distance(
            dist_start_to_abeam, track_1, tas_kt, wind_dir, wind_speed_kt
        )

        # Leg 2: Downwind leg from ABEAM (opposite runway heading - tailwind typically)
        track_2_downwind = _wrap_360(runway_heading + 180.0)
        dist_2_corrected = _wind_corrected_glide_distance(
            po180_downwind_leg, track_2_downwind, tas_kt, wind_dir, wind_speed_kt
        )

        # Leg 3: PO180 turn arc (180° turn through base)
        # Average track through the 180° turn is roughly perpendicular to runway
        if pattern_side == "left":
            track_3_avg = _wrap_360(runway_heading + 90.0)  # Left pattern base turn direction
        else:
            track_3_avg = _wrap_360(runway_heading - 90.0)  # Right pattern base turn direction
        dist_3_corrected = _wind_corrected_glide_distance(
            po180_turn_arc, track_3_avg, tas_kt, wind_dir, wind_speed_kt
        )

        # Leg 4: Final approach (into wind - runway heading)
        track_4 = runway_heading
        dist_4_corrected = _wind_corrected_glide_distance(
            po180_final_leg, track_4, tas_kt, wind_dir, wind_speed_kt
        )

        # Total ground track for full spiral flow with wind correction
        spiral_flow_ground_track = dist_1_corrected + dist_2_corrected + dist_3_corrected + dist_4_corrected

        # Minimum altitude to complete full spiral flow
        # Apply safety margin to account for turn inefficiencies and wind variations
        abeam_target_alt = abeam_bucket.altitude_ft
        spiral_flow_min_altitude = ((spiral_flow_ground_track / glide_ratio) * DECISION_TREE_SAFETY_MARGIN
                                    + abeam_target_alt)

        # =======================================================================
        # DECISION
        # =======================================================================

        abeam_top = abeam_bucket.altitude_ft + abeam_bucket.height_ft / 2
        spiral_lower = abeam_top + 500  # Small buffer above ABEAM top
        spiral_upper = 15000.0
        spiral_center = (spiral_lower + spiral_upper) / 2.0
        spiral_height = spiral_upper - spiral_lower

        if start_alt >= spiral_flow_min_altitude:
            # High altitude: Use SPIRAL → ABEAM → PO180 → TOUCHDOWN
            # Aircraft has enough altitude for the full pattern with spiral
            spiral_bucket = Bucket(
                name="SPIRAL",
                lat=abeam_bucket.lat,
                lon=abeam_bucket.lon,
                altitude_ft=spiral_center,
                height_ft=spiral_height,
                width_ft=2000.0,
                depth_ft=2000.0,
                heading_deg=abeam_bucket.heading_deg,
                heading_tol_deg=45.0,
                next_bucket_name="ABEAM",
            )
            return [spiral_bucket, abeam_bucket, touchdown_bucket], pattern_side, False
        else:
            # Low altitude: Skip spiral, go directly to ABEAM → PO180 → TOUCHDOWN
            # Not enough altitude to justify spiral - proceed directly to pattern
            return [abeam_bucket, touchdown_bucket], pattern_side, False


@dataclass
class PositionClassification:
    """Classification of aircraft position relative to runway pattern."""
    position_type: PositionType
    pattern_side: str
    cross_track_ft: float
    along_track_ft: float
    altitude_status: AltitudeStatus
    distance_to_touchdown_ft: float
    bearing_to_touchdown: float
    heading_diff_to_runway: float


@dataclass
class SimulationState:
    """Mutable state for the engine-out simulation."""
    lat: float
    lon: float
    alt_agl: float
    heading: float
    track: float
    ias: float

    time: float = 0.0
    phase: str = PHASE_REACTION

    strategy: Strategy = Strategy.DIRECT_FINAL
    pattern_side: str = "left"

    bank_deg: float = 0.0
    bank_target_deg: float = 0.0

    turn_accumulated_deg: float = 0.0
    turn_target_deg: float = 0.0
    turn_direction: int = 0

    downwind_distance_ft: float = 0.0
    base_turn_started: bool = False
    arc_progress_deg: float = 0.0
    turn_radius_ft: float = 0.0

    s_turn_count: int = 0
    s_turn_direction: int = 1
    s_turn_active: bool = False
    s_turn_phase: str = "none"
    s_turn_target_xtrack: float = 0.0
    orbit_accumulated_deg: float = 0.0
    slip_active: bool = False
    slip_intensity: float = 0.0
    slip_time_sec: float = 0.0

    spiral_turns_completed: float = 0.0
    target_pattern_altitude_ft: float = DEFAULT_PATTERN_ALTITUDE_FT

    have_it_made: bool = False
    excess_altitude_ft: float = 0.0

    min_speed_margin_kt: float = float('inf')
    max_bank_used_deg: float = 0.0
    phase_times: Dict[str, float] = field(default_factory=dict)

    wn_fps: float = 0.0
    we_fps: float = 0.0


def _get_stall_speed(ac: dict, weight_lbs: float, config: str = "clean") -> float:
    """Get stall speed adjusted for weight."""
    stall_speeds = ac.get("stall_speeds", {})
    config_data = stall_speeds.get(config, stall_speeds.get("clean", {}))

    weights = config_data.get("weights", [2000])
    speeds = config_data.get("speeds", [50])

    if not weights or not speeds:
        return 50.0

    if weight_lbs <= weights[0]:
        return float(speeds[0])
    if weight_lbs >= weights[-1]:
        return float(speeds[-1])

    for i in range(len(weights) - 1):
        if weights[i] <= weight_lbs <= weights[i + 1]:
            ratio = (weight_lbs - weights[i]) / (weights[i + 1] - weights[i])
            return speeds[i] + ratio * (speeds[i + 1] - speeds[i])

    return float(speeds[-1])


def _get_vmca(ac: dict, engine_option: str = None) -> Optional[float]:
    """Get Vmca for multi-engine aircraft."""
    if ac.get("engine_count", 1) <= 1:
        return None
    vmca = ac.get("vmca_kias")
    if vmca is not None:
        return float(vmca)
    if engine_option:
        engines = ac.get("engine_options", {})
        if engine_option in engines:
            vmca = engines[engine_option].get("vmca_kias")
            if vmca is not None:
                return float(vmca)
    return None


def _compute_wind_correction_angle(
    desired_track_deg: float,
    tas_fps: float,
    wn_fps: float,
    we_fps: float,
) -> Tuple[float, float, float]:
    """Solve wind triangle. Returns: (heading_deg, groundspeed_kt, drift_deg)"""
    trk_rad = math.radians(_wrap_360(desired_track_deg))

    w_cross = (-wn_fps * math.sin(trk_rad)) + (we_fps * math.cos(trk_rad))
    w_head = (wn_fps * math.cos(trk_rad)) + (we_fps * math.sin(trk_rad))

    if tas_fps > 1.0:
        wca_ratio = max(-1.0, min(1.0, w_cross / tas_fps))
        wca_rad = math.asin(wca_ratio)
    else:
        wca_rad = 0.0

    drift_deg = math.degrees(wca_rad)
    heading_deg = _wrap_360(desired_track_deg + drift_deg)

    gs_fps = tas_fps * math.cos(wca_rad) + w_head
    gs_fps = max(1.0, gs_fps)
    gs_kt = fps_to_knots(gs_fps)

    return heading_deg, gs_kt, drift_deg


def _get_min_safe_speed(
    ac: dict,
    weight_lbs: float,
    bank_deg: float,
    engine_option: str = None,
    flap_config: str = "clean",
) -> Tuple[float, str]:
    """Get minimum safe speed. Returns: (min_speed_kias, limiting_factor)"""
    vs = _get_stall_speed(ac, weight_lbs, flap_config)
    n = compute_load_factor(abs(bank_deg)) if abs(bank_deg) > 1.0 else 1.0
    vs_turn = compute_stall_speed(vs, n)
    min_stall = vs_turn * 1.1

    vmca = _get_vmca(ac, engine_option)
    if vmca is not None and vmca > min_stall:
        return vmca, "vmca"
    return min_stall, "stall"


def _calculate_required_altitude(
    dist_to_touchdown_ft: float,
    glide_ratio: float,
    safety_margin: float = 1.0,
) -> float:
    """Calculate altitude needed to glide a given distance."""
    return (dist_to_touchdown_ft / glide_ratio) * safety_margin


def _calculate_glidepath_altitude(
    dist_to_touchdown_ft: float,
    glidepath_angle_deg: float = GLIDEPATH_ANGLE_DEG,
) -> float:
    """Calculate altitude for standard glidepath at given distance."""
    return dist_to_touchdown_ft * math.tan(math.radians(glidepath_angle_deg))


def _calculate_slip_for_touchdown(
    current_altitude_ft: float,
    distance_to_touchdown_ft: float,
    straight_glide_ratio: float,
    min_glide_ratio: float = 3.0,
) -> Tuple[float, float]:
    """Calculate slip intensity needed to hit the touchdown point exactly."""
    if current_altitude_ft <= 0 or distance_to_touchdown_ft <= 0:
        return 0.0, straight_glide_ratio

    required_gr = distance_to_touchdown_ft / current_altitude_ft

    if required_gr >= straight_glide_ratio:
        return 0.0, straight_glide_ratio

    min_slip_gr = straight_glide_ratio * (1.0 - SLIP_GR_REDUCTION)
    min_slip_gr = max(min_glide_ratio, min_slip_gr)

    if required_gr <= min_slip_gr:
        return 1.0, min_slip_gr

    gr_range = straight_glide_ratio - min_slip_gr
    gr_reduction_needed = straight_glide_ratio - required_gr
    slip_intensity = gr_reduction_needed / gr_range if gr_range > 0 else 0.0
    slip_intensity = max(0.0, min(1.0, slip_intensity))

    effective_gr = straight_glide_ratio * (1.0 - slip_intensity * SLIP_GR_REDUCTION)
    effective_gr = max(min_glide_ratio, effective_gr)

    return slip_intensity, effective_gr


# =============================================================================
# POSITION CLASSIFICATION
# =============================================================================

def classify_position(
    current_point: GeoPoint,
    current_heading: float,
    current_altitude_agl: float,
    touchdown_point: GeoPoint,
    touchdown_heading: float,
    glide_ratio: float,
    pattern_offset_ft: float = DEFAULT_PATTERN_OFFSET_FT,
    pattern_altitude_ft: float = DEFAULT_PATTERN_ALTITUDE_FT,
) -> PositionClassification:
    """Classify aircraft position relative to runway pattern."""
    cross_track_ft, along_track_ft = _cross_track_to_centerline_ft(
        touchdown_point, current_point, touchdown_heading
    )

    dist_to_td_ft = geo_dist(
        (current_point.latitude, current_point.longitude),
        (touchdown_point.latitude, touchdown_point.longitude)
    ).feet

    bearing_to_td = calculate_initial_compass_bearing(current_point, touchdown_point)
    heading_diff = _angle_diff_deg(current_heading, touchdown_heading)
    pattern_side = "right" if cross_track_ft > 0 else "left"

    required_alt = _calculate_required_altitude(dist_to_td_ft, glide_ratio, 1.0)
    glidepath_alt = _calculate_glidepath_altitude(dist_to_td_ft)

    if current_altitude_agl < required_alt * ALTITUDE_LOW_THRESHOLD:
        altitude_status = AltitudeStatus.LOW
    elif current_altitude_agl > pattern_altitude_ft * ALTITUDE_VERY_HIGH_THRESHOLD:
        altitude_status = AltitudeStatus.VERY_HIGH
    elif current_altitude_agl > glidepath_alt * ALTITUDE_HIGH_THRESHOLD:
        altitude_status = AltitudeStatus.HIGH
    else:
        altitude_status = AltitudeStatus.ON_GLIDEPATH

    abs_cross_track = abs(cross_track_ft)
    abs_heading_diff = abs(heading_diff)

    if (altitude_status == AltitudeStatus.VERY_HIGH and
        abs_cross_track < pattern_offset_ft * 2 and
        abs(along_track_ft) < pattern_offset_ft * 2):
        position_type = PositionType.OVERHEAD
    elif (abs_cross_track < FINAL_CORRIDOR_WIDTH_FT and
          along_track_ft < 0 and
          abs_heading_diff < FINAL_HEADING_TOLERANCE_DEG):
        position_type = PositionType.FINAL
    elif (pattern_offset_ft * 0.5 < abs_cross_track < BASE_LEG_MAX_CROSS_TRACK_FT and
          abs(along_track_ft) < BASE_LEG_NEAR_ABEAM_FT and
          abs(abs_heading_diff - 90) < BASE_HEADING_TOLERANCE_DEG):
        position_type = PositionType.BASE
    elif (pattern_offset_ft * 0.7 < abs_cross_track < pattern_offset_ft * 1.5 and
          abs(along_track_ft) < pattern_offset_ft * 0.3 and
          abs(abs_heading_diff - 180) < DOWNWIND_HEADING_TOLERANCE_DEG):
        position_type = PositionType.ABEAM
    elif (pattern_offset_ft * 0.5 < abs_cross_track < pattern_offset_ft * 1.5 and
          along_track_ft > 0 and
          abs(abs_heading_diff - 180) < DOWNWIND_HEADING_TOLERANCE_DEG):
        position_type = PositionType.DOWNWIND
    else:
        position_type = PositionType.OTHER

    return PositionClassification(
        position_type=position_type,
        pattern_side=pattern_side,
        cross_track_ft=cross_track_ft,
        along_track_ft=along_track_ft,
        altitude_status=altitude_status,
        distance_to_touchdown_ft=dist_to_td_ft,
        bearing_to_touchdown=bearing_to_td,
        heading_diff_to_runway=heading_diff,
    )


# =============================================================================
# GEOMETRY CALCULATIONS
# =============================================================================

def _calculate_bank_for_turn_radius(tas_fps: float, radius_ft: float, min_bank: float = 5.0, max_bank: float = 45.0) -> float:
    """Calculate bank angle needed for a given turn radius."""
    if radius_ft <= 0 or tas_fps <= 0:
        return min_bank

    tan_bank = (tas_fps ** 2) / (G_FPS2 * radius_ft)
    bank_deg = math.degrees(math.atan(tan_bank))
    return max(min_bank, min(max_bank, bank_deg))


def _calculate_turn_radius_for_bank(tas_fps: float, bank_deg: float) -> float:
    """Calculate turn radius for a given bank angle."""
    if bank_deg <= 0 or tas_fps <= 0:
        return float('inf')

    tan_bank = math.tan(math.radians(bank_deg))
    if tan_bank <= 0:
        return float('inf')

    return (tas_fps ** 2) / (G_FPS2 * tan_bank)


def _calculate_required_bank_for_pattern(
    cross_track_ft: float,
    tas_fps: float,
    turn_degrees: float = 180.0,
    min_bank: float = 5.0,
    max_bank: float = 45.0,
) -> Tuple[float, float]:
    """Calculate bank angle and radius needed to complete a turn from current position."""
    abs_cross = abs(cross_track_ft)

    if turn_degrees >= 170:
        required_radius = abs_cross / 2.0
    elif turn_degrees >= 80:
        required_radius = abs_cross
    else:
        required_radius = abs_cross / (2 * math.sin(math.radians(turn_degrees / 2)))

    required_radius = max(100.0, required_radius)
    bank_deg = _calculate_bank_for_turn_radius(tas_fps, required_radius, min_bank, max_bank)

    if bank_deg >= max_bank:
        actual_radius = _calculate_turn_radius_for_bank(tas_fps, max_bank)
        return max_bank, actual_radius

    return bank_deg, required_radius


FINAL_ESTABLISHED_XTRACK_FT = 400.0
FINAL_ESTABLISHED_HEADING_DEG = 30.0
FINAL_CENTERLINE_TARGET_FT = 50.0

S_TURN_LATERAL_OFFSET_FT = 800.0
S_TURN_MIN_EXCESS_ALT_FT = 200.0
S_TURN_BANK_DEG = 30.0

TOUCHDOWN_SUCCESS_MAX_ALT_FT = 100.0


def _calculate_altitude_loss_potential(
    distance_ft: float,
    straight_gr: float,
    with_slip: bool = True,
    with_s_turns: bool = False,
) -> float:
    """Calculate how much altitude we can lose over a given distance."""
    if distance_ft <= 0:
        return 0.0

    effective_gr = straight_gr
    path_multiplier = 1.0

    if with_slip:
        effective_gr = straight_gr * (1.0 - SLIP_GR_REDUCTION)

    if with_s_turns:
        path_multiplier = 1.4

    effective_gr = max(2.0, effective_gr)
    return (distance_ft * path_multiplier) / effective_gr


def _needs_s_turns_on_final(
    altitude_ft: float,
    distance_to_touchdown_ft: float,
    straight_gr: float,
) -> Tuple[bool, float]:
    """Determine if S-turns are needed to lose altitude on final."""
    alt_loss_with_slip = _calculate_altitude_loss_potential(
        distance_to_touchdown_ft, straight_gr, with_slip=True, with_s_turns=False
    )

    projected_alt_at_touchdown = altitude_ft - alt_loss_with_slip

    if projected_alt_at_touchdown > TOUCHDOWN_SUCCESS_MAX_ALT_FT:
        return True, projected_alt_at_touchdown

    return False, projected_alt_at_touchdown


def _is_established_on_final(
    track_deg: float,
    runway_heading_deg: float,
    cross_track_ft: float,
    altitude_ft: float,
    distance_to_touchdown_ft: float,
    glide_ratio: float,
) -> bool:
    """Check if aircraft is established on final approach."""
    heading_err = abs(_angle_diff_deg(track_deg, runway_heading_deg))
    if heading_err > FINAL_ESTABLISHED_HEADING_DEG:
        return False

    if abs(cross_track_ft) > FINAL_ESTABLISHED_XTRACK_FT:
        return False

    return True


# =============================================================================
# MAIN SIMULATION FUNCTION
# =============================================================================

def run_simulation(
    start_point: GeoPoint,
    start_heading: float,
    touchdown_point: GeoPoint,
    touchdown_heading: float,
    ac: dict,
    engine_option: str,
    weight_lbs: float,
    flap_config: str,
    prop_config: str,
    oat_c: float,
    altimeter_inhg: float,
    wind_dir: float,
    wind_speed: float,
    altitude_agl: float,
    touchdown_elev_ft: float = 0.0,
    max_bank_deg: float = 45.0,
    pattern_offset_ft: float = DEFAULT_PATTERN_OFFSET_FT,
    pattern_altitude_ft: float = DEFAULT_PATTERN_ALTITUDE_FT,
    reaction_sec: float = DEFAULT_REACTION_SEC,
    speed_tau_sec: float = DEFAULT_SPEED_TAU_SEC,
    bank_tau_sec: float = DEFAULT_BANK_TAU_SEC,
    timestep_sec: float = DEFAULT_TIMESTEP_SEC,
    force_pattern_side: Optional[str] = None,
    wind_profile: Optional["WindProfile"] = None,  # noqa: F821
) -> Tuple[List[List[float]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Run the engine-out simulation using bucket-based navigation.

    Args:
        force_pattern_side: If provided ("left" or "right"), forces pattern to that side.
                           Enables opposite spiral when start is on opposite side.
    """
    flap_config = _canon_flap_config(flap_config)
    prop_config = _canon_prop_config(prop_config)

    best_glide_kias, straight_gr = _get_best_glide_and_ratio(
        ac, engine_option, flap_config, prop_config
    )

    field_elev_ft = 0.0
    alt_msl_ft = field_elev_ft + float(altitude_agl)
    pressure_alt_ft = compute_pressure_altitude(alt_msl_ft, float(altimeter_inhg))
    rho = compute_air_density(pressure_alt_ft, float(oat_c))
    straight_gr = adjust_glide_ratio_for_density(straight_gr, rho)
    straight_gr = max(3.0, min(straight_gr, 25.0))

    tas_knots = compute_true_airspeed(best_glide_kias, pressure_alt_ft, float(oat_c))
    tas_fps = max(1.0, knots_to_fps(tas_knots))

    # Phase H · use the live winds-aloft column when provided. The
    # engine_out sim is segment-based (not tick-based), so per-tick
    # wind threading is a future refactor (~one bucket = one wind sample
    # using `wind_profile.at(bucket_mid_alt_msl)` would be the natural
    # split). Iteration 1: compute the wind at the GLIDE'S MEAN altitude
    # and use that for the whole simulation.
    #
    # 2026-05-21: the user-supplied wind_dir / wind_speed are treated as
    # the surface wind. When a column is available, we override its SFC
    # layer to the user's values before sampling the mean so the pilot's
    # sidebar edits are honored (previously this branch silently
    # clobbered them with the column's surface layer).
    wind_layers_used: list[tuple[float, float, float]] = []
    if wind_profile is not None:
        try:
            wind_profile = wind_profile.with_surface_override(
                float(wind_dir), float(wind_speed),
                surface_alt_ft_msl=float(touchdown_elev_ft),
            )
        except Exception:
            pass  # fall through to the unmodified profile
        try:
            wind_layers_used = wind_profile.layers()
        except Exception:
            wind_layers_used = []
        # Mean glide altitude MSL: (touchdown_elev + failure_alt_msl)/2.
        mean_alt_msl = (float(touchdown_elev_ft) + alt_msl_ft) / 2.0
        try:
            wd_eff, ws_eff = wind_profile.at(mean_alt_msl)
            wind_dir = float(wd_eff)
            wind_speed = float(ws_eff)
        except Exception:
            pass  # fall through to the static args

    wn_fps, we_fps = _wind_components_from_dir(float(wind_dir), float(wind_speed))

    buckets, pattern_side, use_opposite_spiral = _build_bucket_chain(
        start_point, float(altitude_agl), float(start_heading),
        touchdown_point, float(touchdown_heading),
        pattern_offset_ft, pattern_altitude_ft, straight_gr,
        force_pattern_side=force_pattern_side,
        wind_dir=float(wind_dir),
        wind_speed_kt=float(wind_speed),
        tas_kt=tas_knots,
        max_bank_deg=float(max_bank_deg),
    )

    lat = start_point.latitude
    lon = start_point.longitude
    alt_agl = float(altitude_agl)
    heading = float(start_heading)
    track = heading
    ias = ac.get("Vy", best_glide_kias * 1.1)
    bank_deg = 0.0
    time_sec = 0.0
    dt = float(timestep_sec)

    current_bucket_idx = 0
    if len(buckets) >= 2 and buckets[0].name == "SPIRAL":
        spiral_bucket = buckets[0]
        spiral_lower = spiral_bucket.altitude_ft - spiral_bucket.height_ft / 2
        if alt_agl < spiral_lower:
            current_bucket_idx = 1

    # NOTE: For OPPOSITE_SPIRAL, we do NOT skip based on altitude
    # The aircraft must fly to OPPOSITE_SPIRAL's lateral position first,
    # then the decision tree handles altitude management (full spirals vs half-spiral to ABEAM)

    # For FINAL_SPIRAL: skip if altitude is already low enough for direct approach to FINAL
    if len(buckets) >= 2 and buckets[0].name == "FINAL_SPIRAL":
        final_bucket = buckets[1] if buckets[1].name == "FINAL" else None
        if final_bucket:
            final_top = final_bucket.altitude_ft + final_bucket.height_ft / 2
            if alt_agl <= final_top + 500:  # Within ~500ft of FINAL bucket altitude range
                current_bucket_idx = 1

    in_spiral = False
    spiral_turns = 0.0
    spiral_completed_count = 0
    spirals_needed = 0
    target_radius = pattern_offset_ft
    alt_to_lose = 0.0

    # Opposite spiral state machine
    # Phases: "full_spiral" (360° to lose altitude) or "half_spiral_to_abeam" (180° arc to ABEAM)
    in_opposite_spiral = False
    opposite_spiral_phase = "deciding"  # "deciding", "full_spiral", "half_spiral_to_abeam"
    opposite_spiral_turns = 0.0
    opposite_spiral_direction = 1
    opposite_spiral_radius = 0.0
    opposite_spiral_target_point = None  # ABEAM bucket center

    # Half-spiral arc state (PO180-style: outbound leg + 180° turn to ABEAM)
    half_spiral_phase = "outbound"  # "outbound", "turn", "inbound"
    half_spiral_outbound_heading = 0.0
    half_spiral_outbound_dist_needed = 0.0
    half_spiral_outbound_flown = 0.0
    half_spiral_turn_accumulated = 0.0
    half_spiral_turn_radius = 0.0

    # Legacy half-spiral variables (kept for compatibility)
    in_half_spiral = False
    half_spiral_turns = 0.0
    half_spiral_target_turns = 0.5
    half_spiral_direction = 1

    in_po180 = False
    po180_phase = "downwind"
    po180_turn_accumulated = 0.0
    po180_downwind_extension = 0.0
    po180_downwind_flown = 0.0
    max_slip_used = 0.0
    max_bank_used = 0.0
    phase_times = {}

    # Final-side spiral state (Option B: medium altitude on final side)
    in_final_spiral = False
    final_spiral_turns = 0.0
    final_spiral_direction = 1  # 1 for right, -1 for left
    final_spiral_radius = 0.0
    final_spiral_target_alt = 0.0  # Target altitude to exit spiral

    path = [[lat, lon]]
    hover_data = []

    hover_data.append({
        "time": 0.0,
        "phase": "Engine Failure",
        "bucket": buckets[0].name if buckets else "none",
        "alt": alt_agl,
        "ias": ias,
        "tas": tas_knots,
        "gs": tas_knots,
        "heading": heading,
        "track": track,
        "aob": 0.0,
        "drift": 0.0,
        "vs": 0.0,
        "slip_pct": 0,
        "glide_ratio": straight_gr,
        "load_factor": ((1.0 / math.cos(math.radians(0.0))) if abs(0.0) < 89.9 else None),
        "segment": "Engine Failure",
        })

    reaction_end = reaction_sec
    max_iterations = int(MAX_SIM_TIME_SEC / dt)

    for _ in range(max_iterations):
        if current_bucket_idx >= len(buckets):
            break

        current_bucket = buckets[current_bucket_idx]
        cur_pos = GeoPoint(lat, lon)

        if current_bucket.name == "TOUCHDOWN":
            dist_to_td = geo_dist((lat, lon), (current_bucket.lat, current_bucket.lon)).feet
            if dist_to_td < BUCKET_TOUCHDOWN_DEPTH and alt_agl < BUCKET_TOUCHDOWN_HEIGHT:
                path.append([current_bucket.lat, current_bucket.lon])
                hover_data.append({
                    "time": time_sec,
                    "phase": "touchdown",
                    "bucket": "TOUCHDOWN",
                    "alt": 0.0,
                    "ias": ias,
                    "tas": tas_knots,
                    "gs": tas_knots,
                    "heading": heading,
                    "track": track,
                    "aob": 0.0,
                    "drift": 0.0,
                    "vs": 0.0,
                    "slip_pct": 0,
                    "glide_ratio": straight_gr,
                    "load_factor": ((1.0 / math.cos(math.radians(0.0))) if abs(0.0) < 89.9 else None),
                    "segment": "touchdown",
        })
                break

        if alt_agl <= 0:
            break

        if not in_spiral and not in_opposite_spiral and not in_half_spiral and not in_po180 and not in_final_spiral:
            bucket_captured = current_bucket.contains(lat, lon, alt_agl, track, current_bucket.heading_deg)

            if bucket_captured and current_bucket.name == "SPIRAL":
                abeam_bucket = None
                for b in buckets:
                    if b.name == "ABEAM":
                        abeam_bucket = b
                        break

                if abeam_bucket and alt_agl > abeam_bucket.altitude_ft + abeam_bucket.height_ft / 2:
                    in_spiral = True
                    spiral_turns = 0.0

                    abeam_target_alt = abeam_bucket.altitude_ft
                    initial_alt_to_lose = alt_agl - abeam_target_alt
                    max_spiral_radius_ft = 6000.0
                    min_spiral_radius_ft = 500.0

                    spirals_needed = 1
                    while spirals_needed <= 10:
                        required_radius = (initial_alt_to_lose * straight_gr) / (spirals_needed * 2 * math.pi)
                        if required_radius <= max_spiral_radius_ft:
                            break
                        spirals_needed += 1

                    target_radius = max(min_spiral_radius_ft, min(max_spiral_radius_ft, required_radius))
                    alt_to_lose = initial_alt_to_lose
                else:
                    current_bucket_idx += 1
                    if current_bucket_idx >= len(buckets):
                        break

            # OPPOSITE_SPIRAL capture - aircraft is on opposite side from pattern
            elif bucket_captured and current_bucket.name == "OPPOSITE_SPIRAL":
                abeam_bucket = None
                for b in buckets:
                    if b.name == "ABEAM":
                        abeam_bucket = b
                        break

                if abeam_bucket and alt_agl > abeam_bucket.altitude_ft + abeam_bucket.height_ft / 2:
                    # Enter opposite spiral decision mode
                    in_opposite_spiral = True
                    opposite_spiral_turns = 0.0
                    opposite_spiral_target_point = GeoPoint(abeam_bucket.lat, abeam_bucket.lon)

                    # DECISION: Can we reach ABEAM in one half-spiral (180°) with slip?
                    # Half-spiral geometry:
                    # - Diameter = distance from current position to ABEAM
                    # - Radius = distance / 2
                    # - Turn center = midpoint between aircraft and ABEAM
                    # - Arc length = π * radius
                    dist_to_abeam = geo_dist((lat, lon), (abeam_bucket.lat, abeam_bucket.lon)).feet
                    half_spiral_radius = dist_to_abeam / 2.0
                    half_spiral_arc_length = math.pi * half_spiral_radius

                    # Determine turn direction: shortest path toward ABEAM
                    bearing_to_abeam = calculate_initial_compass_bearing(cur_pos, opposite_spiral_target_point)

                    # Wind-correct arc length using perpendicular to bearing as average track
                    # (half-spiral sweeps 180° so average track is perpendicular to start/end bearing)
                    avg_track_half_spiral = _wrap_360(bearing_to_abeam + 90.0)
                    half_spiral_arc_wc = _wind_corrected_glide_distance(
                        half_spiral_arc_length, avg_track_half_spiral, fps_to_knots(tas_fps), wind_dir, wind_speed
                    )

                    # Calculate altitude loss with maximum slip
                    min_gr_with_slip = straight_gr * (1.0 - SLIP_GR_REDUCTION)
                    min_gr_with_slip = max(3.0, min_gr_with_slip)
                    alt_loss_half_spiral_with_slip = half_spiral_arc_wc / min_gr_with_slip

                    # Target altitude at ABEAM (middle of bucket)
                    abeam_target_alt = abeam_bucket.altitude_ft
                    abeam_top = abeam_bucket.altitude_ft + abeam_bucket.height_ft / 2
                    abeam_bottom = abeam_bucket.altitude_ft - abeam_bucket.height_ft / 2

                    # Altitude we'd arrive at after half-spiral with slip
                    arrival_alt = alt_agl - alt_loss_half_spiral_with_slip
                    turn_diff = _angle_diff_deg(bearing_to_abeam, track)
                    opposite_spiral_direction = 1 if turn_diff > 0 else -1

                    # Calculate EXTENDED half-spiral geometry (with outbound/inbound legs like PO180)
                    # This allows burning excess altitude without requiring a full 360°

                    # Current cross-track and along-track distances to ABEAM
                    angle_off = abs(_angle_diff_deg(bearing_to_abeam, track))
                    cross_track_to_abeam = dist_to_abeam * math.sin(math.radians(min(90.0, angle_off)))
                    along_track_to_abeam = dist_to_abeam * math.cos(math.radians(min(90.0, angle_off)))

                    # Minimum path (no outbound extension): turn arc + inbound
                    min_turn_radius = max(100.0, cross_track_to_abeam / 2.0)
                    min_turn_arc = math.pi * min_turn_radius
                    min_path_length = min_turn_arc + along_track_to_abeam

                    # Calculate altitude we'd arrive at if flying min_path with NORMAL GR
                    # Use straight_gr (not slip GR) because actual execution may not use max slip
                    # This is conservative - predicts less altitude loss, more likely to add extensions
                    alt_loss_min_path = min_path_length / straight_gr
                    expected_arrival_alt = alt_agl - alt_loss_min_path

                    # If we'd arrive ABOVE target, we need outbound extension to burn excess altitude
                    if expected_arrival_alt > abeam_target_alt:
                        # Calculate how much more distance we need to fly (using normal GR)
                        extra_alt_to_lose = expected_arrival_alt - abeam_target_alt
                        extra_distance_needed = extra_alt_to_lose * straight_gr

                        # Distribute extra distance as outbound extension
                        # Path = outbound + turn_arc + inbound
                        # With outbound D: total = D + π×(cross_track + D)/2 + along_track
                        # Extra distance from D: D + π×D/2 = D×(1 + π/2)
                        # So: D = extra_distance_needed / (1 + π/2)
                        outbound_dist_needed = extra_distance_needed / (1.0 + math.pi / 2.0)

                        # With outbound extension, recalculate geometry
                        extended_cross_track = cross_track_to_abeam + outbound_dist_needed
                        extended_turn_radius = max(100.0, extended_cross_track / 2.0)
                    else:
                        # No extension needed - min path loses enough altitude
                        outbound_dist_needed = 0.0
                        extended_turn_radius = min_turn_radius

                    # Calculate required AOB for the (possibly extended) turn radius
                    tan_bank_required = (tas_fps ** 2) / (G_FPS2 * extended_turn_radius)
                    required_aob = math.degrees(math.atan(tan_bank_required))

                    # Geometry is achievable if:
                    # 1. AOB <= 45° (turn not too tight)
                    # 2. Expected arrival altitude >= abeam_bottom (won't arrive too low with min path)
                    # 3. Outbound extension is SLIGHT (like PO180 downwind adjustment, not massive)
                    #    If more altitude needs burning, use full 360° spiral instead
                    max_outbound_extension = min(2000.0, dist_to_abeam * 0.3)  # Max 2000ft or 30% of distance

                    geometry_achievable = (
                        required_aob <= 45.0 and
                        expected_arrival_alt >= abeam_bottom and
                        outbound_dist_needed <= max_outbound_extension
                    )

                    if geometry_achievable:
                        # YES - Use half-spiral with slight extension (like PO180 downwind adjustment)
                        opposite_spiral_phase = "half_spiral_to_abeam"

                        # Store geometry parameters
                        half_spiral_turn_radius = extended_turn_radius
                        half_spiral_outbound_dist_needed = outbound_dist_needed

                        # Outbound heading: perpendicular to bearing to ABEAM
                        abeam_point = GeoPoint(abeam_bucket.lat, abeam_bucket.lon)
                        bearing_to_abeam_init = calculate_initial_compass_bearing(cur_pos, abeam_point)

                        # Outbound direction depends on turn direction
                        if opposite_spiral_direction > 0:
                            # Will turn right, so fly outbound to the left first
                            half_spiral_outbound_heading = _wrap_360(bearing_to_abeam_init - 90.0)
                        else:
                            # Will turn left, so fly outbound to the right first
                            half_spiral_outbound_heading = _wrap_360(bearing_to_abeam_init + 90.0)

                        half_spiral_phase = "outbound"
                        half_spiral_outbound_flown = 0.0
                        half_spiral_turn_accumulated = 0.0
                    else:
                        # NO - Extended half-spiral not achievable, need full 360° spiral first
                        opposite_spiral_phase = "full_spiral"

                        # Size the spiral to burn excess altitude in ~1 turn
                        # This keeps the spiral compact, preserving glide for half spiral + PO180
                        excess_alt = (expected_arrival_alt - abeam_target_alt) if expected_arrival_alt > abeam_target_alt else 500.0

                        # circumference = excess_alt * straight_gr, radius = circumference / (2π)
                        target_spiral_circumference = excess_alt * straight_gr
                        target_spiral_radius = target_spiral_circumference / (2.0 * math.pi)

                        # Clamp to reasonable bounds (500-2500 ft) - allow tight spirals when needed
                        opposite_spiral_radius = max(500.0, min(2500.0, target_spiral_radius))
                else:
                    current_bucket_idx += 1
                    if current_bucket_idx >= len(buckets):
                        break

            # FINAL_SPIRAL capture - aircraft on final side with medium altitude (Option B)
            elif bucket_captured and current_bucket.name == "FINAL_SPIRAL":
                # Find the FINAL bucket to calculate target altitude
                final_bucket = None
                for b in buckets:
                    if b.name == "FINAL":
                        final_bucket = b
                        break

                if final_bucket:
                    final_top = final_bucket.altitude_ft + final_bucket.height_ft / 2

                    # Don't spiral if a straight glide from here would
                    # arrive at FINAL's altitude band. The old check
                    # only compared current altitude to final_top — it
                    # didn't account for how far away FINAL is. Result:
                    # if the aircraft reached the FINAL_SPIRAL bucket
                    # with excess altitude but ALSO with a lot of
                    # ground still to cover (because FINAL is 1.5+ NM
                    # ahead), the spiral fired unnecessarily and burned
                    # off the altitude the aircraft actually needed for
                    # the long glide-in. Use _can_arrive_at_bucket_altitude
                    # — same tolerance the bucket builder uses for
                    # Option A — to short-circuit when direct glide
                    # already lands at the right altitude.
                    can_direct = _can_arrive_at_bucket_altitude(
                        cur_pos, alt_agl, final_bucket, straight_gr,
                        tolerance_ft=500.0,
                        tas_kt=fps_to_knots(tas_fps),
                        wind_dir=wind_dir,
                        wind_speed_kt=wind_speed,
                    )

                    if alt_agl > final_top + 200 and not can_direct:
                        in_final_spiral = True
                        final_spiral_turns = 0.0
                        final_spiral_target_alt = final_bucket.altitude_ft + final_bucket.height_ft / 4

                        # Calculate spiral size based on altitude to lose
                        alt_to_lose_fs = alt_agl - final_spiral_target_alt
                        glide_distance_needed = alt_to_lose_fs * straight_gr

                        # Cap the spiral radius. Old code allowed up
                        # to 5000 ft — for the user-reported KDYB /
                        # 3800 ft case that picked a 1583 ft radius
                        # "spiral" that was really a wide arc. The
                        # aircraft completed only ⅓ of the loop before
                        # the exit conditions fired, drifting ~1800 ft
                        # farther from TD in the process and blowing
                        # the rest of the glide budget on getting back.
                        # Smaller radius → tighter turn rate → exit
                        # conditions fire near the same physical
                        # position even if mid-turn. 600 ft min keeps
                        # the calculated bank under the 45° cap at
                        # typical GA TAS (132 fps → atan(132²/(g·600))
                        # ≈ 42°).
                        max_spiral_radius = 1200.0
                        min_spiral_radius = 600.0

                        n_turns_estimate = 2
                        while n_turns_estimate <= 8:
                            radius_needed = glide_distance_needed / (n_turns_estimate * 2 * math.pi)
                            if radius_needed <= max_spiral_radius:
                                break
                            n_turns_estimate += 1

                        final_spiral_radius = max(min_spiral_radius, min(max_spiral_radius, radius_needed))

                        # Turn direction: prefer to turn away from runway centerline
                        # This keeps the spiral on the extended final side
                        xtrack_ft_fs, _ = _cross_track_to_centerline_ft(
                            touchdown_point, cur_pos, touchdown_heading
                        )
                        # Turn away from centerline to stay on the same side
                        final_spiral_direction = -1 if xtrack_ft_fs >= 0 else 1
                    else:
                        # Already low enough, skip to FINAL
                        current_bucket_idx += 1
                        if current_bucket_idx >= len(buckets):
                            break
                else:
                    current_bucket_idx += 1
                    if current_bucket_idx >= len(buckets):
                        break

            if bucket_captured and current_bucket.name == "ABEAM" or \
               (not in_spiral and not in_opposite_spiral and not in_half_spiral and not in_final_spiral and current_bucket_idx < len(buckets) and buckets[current_bucket_idx].name == "ABEAM"):
                abeam_bucket = buckets[current_bucket_idx]
                if abeam_bucket.contains(lat, lon, alt_agl, track, abeam_bucket.heading_deg):
                    remaining_glide_ft = alt_agl * straight_gr

                    min_turn_radius = (tas_fps ** 2) / (G_FPS2 * math.tan(math.radians(45.0)))
                    min_turn_arc = math.pi * min_turn_radius
                    min_final = pattern_offset_ft * 0.8

                    available_for_downwind = remaining_glide_ft - min_turn_arc - min_final

                    po180_downwind_extension = max(0, available_for_downwind)
                    po180_turn_radius = min_turn_radius

                    in_po180 = True
                    po180_turn_accumulated = 0.0
                    current_bucket_idx += 1
                    if current_bucket_idx >= len(buckets):
                        break

            elif bucket_captured:
                current_bucket_idx += 1
                if current_bucket_idx >= len(buckets):
                    break
                continue

        if time_sec < reaction_end:
            phase_name = "reaction"
        elif in_spiral:
            phase_name = "spiral"
        elif in_opposite_spiral:
            if opposite_spiral_phase == "full_spiral":
                phase_name = "opposite_spiral"
            elif opposite_spiral_phase == "half_spiral_to_abeam":
                phase_name = "half_oval"
            else:
                phase_name = "opposite_spiral"
        elif in_final_spiral:
            phase_name = "final_spiral"
        elif in_half_spiral:
            phase_name = "half_spiral"
        elif in_po180:
            phase_name = po180_phase  # "downwind", "turn", or "final"
        else:
            phase_name = "direct"

        if phase_name not in phase_times:
            phase_times[phase_name] = 0.0
        phase_times[phase_name] += dt

        ias += (best_glide_kias - ias) * min(1.0, dt / speed_tau_sec)

        target_bucket = buckets[min(current_bucket_idx, len(buckets) - 1)]
        target_pos = GeoPoint(target_bucket.lat, target_bucket.lon)


        if in_spiral:
            bearing_from_td = calculate_initial_compass_bearing(touchdown_point, cur_pos)

            dist_from_td = geo_dist(
                (lat, lon),
                (touchdown_point.latitude, touchdown_point.longitude)
            ).feet

            abeam_bucket = None
            for b in buckets:
                if b.name == "ABEAM":
                    abeam_bucket = b
                    break

            abeam_top = abeam_bucket.altitude_ft + abeam_bucket.height_ft / 2 if abeam_bucket else 1600.0

            tan_bank = (tas_fps * tas_fps) / (G_FPS2 * target_radius)
            orbit_bank_deg = math.degrees(math.atan(tan_bank))

            if pattern_side == "left":
                orbit_turn_sign = -1
            else:
                orbit_turn_sign = 1

            # Active orbit guidance (Phase EM-DYN). The legacy
            # bank_target = orbit_turn_sign * orbit_bank_deg sets a constant
            # bank — the aircraft orbits around whatever point its momentum
            # vector projects to at radius R, NOT around the spiral bucket's
            # lat/lon. That works when the aircraft enters the bucket already
            # aligned with the runway centerline (SW/NE quadrant for RWY 04)
            # but offsets the orbit center by ~R for cross-axis entries (NW/SE
            # quadrant). The pursuit law below steers the aircraft toward the
            # tangent of a circle of radius `target_radius` centered at the
            # spiral bucket's lat/lon, with a radial-error correction so the
            # aircraft converges onto the desired orbit instead of just
            # parallelling it.
            spiral_target_bucket = buckets[current_bucket_idx]
            orbit_center = GeoPoint(spiral_target_bucket.lat,
                                      spiral_target_bucket.lon)
            bearing_from_center_to_ac = calculate_initial_compass_bearing(
                orbit_center, cur_pos)
            dist_from_center_ft = geo_dist(
                (lat, lon),
                (spiral_target_bucket.lat, spiral_target_bucket.lon)
            ).feet
            # Tangent direction at aircraft's current position relative to
            # the orbit center. CCW orbit (pattern_side=left) wants tangent
            # pointing 90° CCW from the outward radial.
            if pattern_side == "left":
                tangent_heading = (bearing_from_center_to_ac - 90.0) % 360.0
            else:
                tangent_heading = (bearing_from_center_to_ac + 90.0) % 360.0
            # Radial bias: if aircraft is outside the desired orbit ring,
            # bias the target heading inward (toward the center); if inside,
            # bias outward. 0.15° per ft, capped at ±45° — strong enough to
            # pull a 1000-ft offset down to the orbit ring in ~3 turns
            # rather than ~10.
            radial_error_ft = dist_from_center_ft - target_radius
            radial_bias_deg = max(-45.0, min(45.0, radial_error_ft * 0.15))
            if pattern_side == "left":
                target_heading = (tangent_heading - radial_bias_deg) % 360.0
            else:
                target_heading = (tangent_heading + radial_bias_deg) % 360.0
            # Steady-state bank toward orbit + proportional correction on
            # heading error. The result rolls in aggressively when entering
            # the orbit at an off-tangent heading, then settles to steady
            # orbit_bank_deg once on the circle.
            heading_err = _angle_diff_deg(target_heading, heading)
            bank_target = (orbit_turn_sign * orbit_bank_deg
                            + heading_err * 0.5)
            # Clamp to physical bank envelope.
            bank_target = max(-max_bank_deg,
                                min(max_bank_deg, bank_target))

            abeam_bucket = None
            for b in buckets:
                if b.name == "ABEAM":
                    abeam_bucket = b
                    break
            if abeam_bucket is None:
                abeam_bucket = target_bucket

            dist_to_abeam = geo_dist((lat, lon), (abeam_bucket.lat, abeam_bucket.lon)).feet
            bearing_to_aircraft = calculate_initial_compass_bearing(
                GeoPoint(abeam_bucket.lat, abeam_bucket.lon), cur_pos
            )

            angle_diff = math.radians(_angle_diff_deg(bearing_to_aircraft, abeam_bucket.heading_deg))
            along_track_ft = dist_to_abeam * math.cos(angle_diff)
            cross_track_ft = abs(dist_to_abeam * math.sin(angle_diff))

            abeam_top = abeam_bucket.altitude_ft + abeam_bucket.height_ft / 2
            abeam_bottom = abeam_bucket.altitude_ft - abeam_bucket.height_ft / 2

            half_width = abeam_bucket.width_ft / 2
            half_depth = abeam_bucket.depth_ft / 2
            in_cross_track = cross_track_ft <= half_width
            in_along_track = abs(along_track_ft) <= half_depth
            in_altitude = abeam_bottom <= alt_agl <= abeam_top

            heading_diff = abs(_angle_diff_deg(track, abeam_bucket.heading_deg))
            heading_aligned = heading_diff <= abeam_bucket.heading_tol_deg

            if in_cross_track and in_along_track and in_altitude and heading_aligned:
                in_spiral = False
                in_po180 = True
                po180_phase = "downwind"
                po180_downwind_flown = 0.0
                remaining_glide = alt_agl * straight_gr
                turn_radius = (tas_fps ** 2) / (G_FPS2 * math.tan(math.radians(30.0)))
                turn_arc = math.pi * turn_radius
                final_dist = pattern_offset_ft * 0.5
                po180_downwind_extension = max(0, remaining_glide - turn_arc - final_dist - 500)
                current_bucket_idx = len(buckets) - 1

            if spiral_turns >= 6.0:
                in_spiral = False
                in_po180 = True
                po180_phase = "downwind"
                po180_downwind_flown = 0.0
                remaining_glide = alt_agl * straight_gr
                turn_radius = (tas_fps ** 2) / (G_FPS2 * math.tan(math.radians(30.0)))
                turn_arc = math.pi * turn_radius
                final_dist = pattern_offset_ft * 0.5
                po180_downwind_extension = max(0, remaining_glide - turn_arc - final_dist - 500)
                current_bucket_idx = len(buckets) - 1

            if abs(bank_deg) > 0.5:
                turn_rate = (G_FPS2 * math.tan(math.radians(abs(bank_deg)))) / max(1.0, tas_fps)
                spiral_turns += math.degrees(turn_rate * dt) / 360.0

            current_completed = int(spiral_turns)
            if current_completed > spiral_completed_count:
                spiral_completed_count = current_completed

                abeam_optimal_alt = abeam_bucket.altitude_ft + abeam_bucket.height_ft / 4 if abeam_bucket else 1200.0
                remaining_alt_to_lose = alt_agl - abeam_optimal_alt

                if remaining_alt_to_lose > 0:
                    max_spiral_radius_ft = 6000.0
                    min_spiral_radius_ft = 500.0

                    spirals_needed = 1
                    while spirals_needed <= 10:
                        required_radius = (remaining_alt_to_lose * straight_gr) / (spirals_needed * 2 * math.pi)
                        if required_radius <= max_spiral_radius_ft:
                            break
                        spirals_needed += 1

                    target_radius = max(min_spiral_radius_ft, min(max_spiral_radius_ft, required_radius))
                    alt_to_lose = remaining_alt_to_lose

                    tan_bank = (tas_fps * tas_fps) / (G_FPS2 * target_radius)
                    orbit_bank_deg = math.degrees(math.atan(tan_bank))

        elif in_final_spiral:
            # FINAL SPIRAL: Spiral descent on the final side until altitude allows straight-to-final
            # This is Option B for final-side starts with medium altitude

            # Find the FINAL bucket to check transition altitude
            final_bucket_fs = None
            for b in buckets:
                if b.name == "FINAL":
                    final_bucket_fs = b
                    break

            if final_bucket_fs:
                final_top = final_bucket_fs.altitude_ft + final_bucket_fs.height_ft / 2
                final_center_alt = final_bucket_fs.altitude_ft

                # Calculate bank angle for the spiral
                tan_bank_fs = (tas_fps * tas_fps) / (G_FPS2 * final_spiral_radius)
                orbit_bank_deg_fs = math.degrees(math.atan(tan_bank_fs))
                orbit_bank_deg_fs = max(15.0, min(45.0, orbit_bank_deg_fs))

                bank_target = final_spiral_direction * orbit_bank_deg_fs

                # Track spiral turns
                if abs(bank_deg) > 0.5:
                    turn_rate_fs = (G_FPS2 * math.tan(math.radians(abs(bank_deg)))) / max(1.0, tas_fps)
                    final_spiral_turns += math.degrees(turn_rate_fs * dt) / 360.0

                # Calculate distance to FINAL bucket
                dist_to_final = geo_dist((lat, lon), (final_bucket_fs.lat, final_bucket_fs.lon)).feet

                # Also check: are we roughly pointed toward touchdown?
                bearing_to_final = calculate_initial_compass_bearing(cur_pos, GeoPoint(final_bucket_fs.lat, final_bucket_fs.lon))

                # Wind-correct distance for consistent ground track model
                dist_to_final_wc = _wind_corrected_glide_distance(
                    dist_to_final, bearing_to_final, fps_to_knots(tas_fps), wind_dir, wind_speed
                )

                # Check if we can glide to FINAL bucket now
                # We need: (current_alt - dist_to_final/glide_ratio) ≈ final bucket altitude
                arrival_alt_if_glide = alt_agl - (dist_to_final_wc / straight_gr)

                # Transition condition: can glide to FINAL at approximately correct altitude
                # Allow some buffer since we can use slip to fine-tune.
                # Tightened from final_top+500 to final_top+200 — the
                # +500 slop let the spiral exit while the aircraft was
                # still well above FINAL's altitude band, leaving slip
                # to absorb 500+ ft of excess on a 0.5 NM final leg
                # which it physically can't.
                can_transition = (arrival_alt_if_glide >= final_bucket_fs.altitude_ft - final_bucket_fs.height_ft / 2 and
                                  arrival_alt_if_glide <= final_top + 200)
                heading_error_to_final = abs(_angle_diff_deg(track, bearing_to_final))
                # Tightened from 90° to 60° — exiting at 89° off meant
                # the aircraft then had to bleed more altitude turning
                # the rest of the way to alignment, blowing the energy
                # budget on the long glide-in.
                roughly_facing_final = heading_error_to_final < 60.0

                if can_transition and roughly_facing_final:
                    # Transition: exit spiral and head to FINAL bucket
                    in_final_spiral = False
                    current_bucket_idx += 1  # Move to FINAL bucket
                    if current_bucket_idx >= len(buckets):
                        break

                # Safety: exit after excessive turns (6 full spirals)
                if final_spiral_turns >= 6.0:
                    in_final_spiral = False
                    current_bucket_idx += 1
                    if current_bucket_idx >= len(buckets):
                        break

                # Adaptive radius adjustment after each complete turn
                current_completed_fs = int(final_spiral_turns)
                if current_completed_fs > 0 and final_spiral_turns - current_completed_fs < dt / 0.5:
                    # Just completed a turn - recalculate radius
                    remaining_alt_to_lose_fs = alt_agl - final_spiral_target_alt
                    if remaining_alt_to_lose_fs > 0:
                        glide_dist_remaining = remaining_alt_to_lose_fs * straight_gr
                        # Estimate turns remaining
                        turns_remaining = max(1, 6 - current_completed_fs)
                        new_radius = glide_dist_remaining / (turns_remaining * 2 * math.pi)
                        final_spiral_radius = max(800.0, min(5000.0, new_radius))

            else:
                # No FINAL bucket found, exit spiral
                in_final_spiral = False
                current_bucket_idx += 1
                if current_bucket_idx >= len(buckets):
                    break

        elif in_opposite_spiral:
            # OPPOSITE SPIRAL STATE MACHINE
            # Phases: "full_spiral" (360° to lose altitude) or "half_spiral_to_abeam" (180° arc to ABEAM)

            abeam_bucket = None
            for b in buckets:
                if b.name == "ABEAM":
                    abeam_bucket = b
                    break

            if abeam_bucket is None:
                abeam_bucket = target_bucket

            # Calculate current geometry to ABEAM
            dist_to_abeam = geo_dist((lat, lon), (abeam_bucket.lat, abeam_bucket.lon)).feet
            bearing_to_abeam = calculate_initial_compass_bearing(cur_pos, GeoPoint(abeam_bucket.lat, abeam_bucket.lon))
            abeam_top = abeam_bucket.altitude_ft + abeam_bucket.height_ft / 2
            abeam_bottom = abeam_bucket.altitude_ft - abeam_bucket.height_ft / 2

            if opposite_spiral_phase == "full_spiral":
                # FULL SPIRAL PHASE: Do 360° turns until half-spiral to ABEAM is achievable

                # Bank for the full spiral - no minimum, let geometry dictate
                tan_bank = (tas_fps * tas_fps) / (G_FPS2 * opposite_spiral_radius)
                orbit_bank_deg = math.degrees(math.atan(tan_bank))
                orbit_bank_deg = min(45.0, orbit_bank_deg)  # Only cap max, no minimum
                bank_target = opposite_spiral_direction * orbit_bank_deg

                # Track turn progress
                if abs(bank_deg) > 0.5:
                    turn_rate = (G_FPS2 * math.tan(math.radians(abs(bank_deg)))) / max(1.0, tas_fps)
                    opposite_spiral_turns += math.degrees(turn_rate * dt) / 360.0

                # After each full turn (360°), re-evaluate: can we reach ABEAM in a half-spiral now?
                if opposite_spiral_turns >= 1.0:
                    opposite_spiral_turns = 0.0  # Reset for next evaluation

                    # Recalculate half-spiral geometry from current position
                    dist_to_abeam = geo_dist((lat, lon), (abeam_bucket.lat, abeam_bucket.lon)).feet
                    half_spiral_radius = dist_to_abeam / 2.0
                    half_spiral_arc_length = math.pi * half_spiral_radius

                    # Wind-correct arc length using perpendicular to bearing as average track
                    bearing_to_abeam_check = calculate_initial_compass_bearing(cur_pos, GeoPoint(abeam_bucket.lat, abeam_bucket.lon))
                    avg_track_half_spiral = _wrap_360(bearing_to_abeam_check + 90.0)
                    half_spiral_arc_wc = _wind_corrected_glide_distance(
                        half_spiral_arc_length, avg_track_half_spiral, fps_to_knots(tas_fps), wind_dir, wind_speed
                    )

                    # Calculate altitude loss with maximum slip
                    min_gr_with_slip = straight_gr * (1.0 - SLIP_GR_REDUCTION)
                    min_gr_with_slip = max(3.0, min_gr_with_slip)
                    alt_loss_half_spiral_with_slip = half_spiral_arc_wc / min_gr_with_slip

                    # Altitude we'd arrive at after half-spiral with slip
                    arrival_alt = alt_agl - alt_loss_half_spiral_with_slip

                    # Calculate EXTENDED half-spiral geometry (with outbound/inbound legs)
                    bearing_to_abeam = calculate_initial_compass_bearing(cur_pos, GeoPoint(abeam_bucket.lat, abeam_bucket.lon))
                    turn_diff = _angle_diff_deg(bearing_to_abeam, track)
                    opposite_spiral_direction = 1 if turn_diff > 0 else -1

                    abeam_target_alt = abeam_bucket.altitude_ft

                    # Current cross-track and along-track distances to ABEAM
                    angle_off = abs(_angle_diff_deg(bearing_to_abeam, track))
                    cross_track_to_abeam = dist_to_abeam * math.sin(math.radians(min(90.0, angle_off)))
                    along_track_to_abeam = dist_to_abeam * math.cos(math.radians(min(90.0, angle_off)))

                    # Minimum path (no outbound extension): turn arc + inbound
                    min_turn_radius = max(100.0, cross_track_to_abeam / 2.0)
                    min_turn_arc = math.pi * min_turn_radius
                    min_path_length = min_turn_arc + along_track_to_abeam

                    # Calculate altitude we'd arrive at if flying min_path with NORMAL GR
                    # Use straight_gr (not slip GR) - conservative prediction
                    alt_loss_min_path = min_path_length / straight_gr
                    expected_arrival_alt = alt_agl - alt_loss_min_path

                    # If we'd arrive ABOVE target, we need outbound extension
                    if expected_arrival_alt > abeam_target_alt:
                        extra_alt_to_lose = expected_arrival_alt - abeam_target_alt
                        extra_distance_needed = extra_alt_to_lose * straight_gr
                        outbound_dist_needed = extra_distance_needed / (1.0 + math.pi / 2.0)
                        extended_cross_track = cross_track_to_abeam + outbound_dist_needed
                        extended_turn_radius = max(100.0, extended_cross_track / 2.0)
                    else:
                        outbound_dist_needed = 0.0
                        extended_turn_radius = min_turn_radius

                    # Calculate required AOB for extended geometry
                    tan_bank_required = (tas_fps ** 2) / (G_FPS2 * extended_turn_radius)
                    required_aob = math.degrees(math.atan(tan_bank_required))

                    # Check if geometry is achievable (extension must be slight, not massive)
                    max_outbound_extension = min(2000.0, dist_to_abeam * 0.3)
                    geometry_achievable = (
                        required_aob <= 45.0 and
                        expected_arrival_alt >= abeam_bottom and
                        outbound_dist_needed <= max_outbound_extension
                    )

                    if geometry_achievable:
                        # YES - Use extended half-spiral
                        opposite_spiral_phase = "half_spiral_to_abeam"
                        opposite_spiral_turns = 0.0

                        half_spiral_turn_radius = extended_turn_radius
                        half_spiral_outbound_dist_needed = outbound_dist_needed

                        # Outbound heading: perpendicular to bearing to ABEAM
                        if opposite_spiral_direction > 0:
                            half_spiral_outbound_heading = _wrap_360(bearing_to_abeam - 90.0)
                        else:
                            half_spiral_outbound_heading = _wrap_360(bearing_to_abeam + 90.0)

                        half_spiral_phase = "outbound"
                        half_spiral_outbound_flown = 0.0
                        half_spiral_turn_accumulated = 0.0
                    else:
                        # Geometry not achievable, stay in full_spiral for another turn
                        # RECALCULATE spiral radius based on current excess altitude
                        excess_alt = (expected_arrival_alt - abeam_target_alt) if expected_arrival_alt > abeam_target_alt else 300.0
                        target_spiral_circumference = excess_alt * straight_gr
                        target_spiral_radius = target_spiral_circumference / (2.0 * math.pi)
                        opposite_spiral_radius = max(500.0, min(2500.0, target_spiral_radius))

            elif opposite_spiral_phase == "half_spiral_to_abeam":
                # HALF SPIRAL TO ABEAM: PO180-style geometry
                # Phase 1: "outbound" - fly perpendicular to ABEAM bearing
                # Phase 2: "turn" - 180° turn
                # Phase 3: "inbound" - fly to ABEAM

                if half_spiral_phase == "outbound":
                    # Fly the outbound heading
                    track_error = _angle_diff_deg(half_spiral_outbound_heading, track)
                    bank_target = max(-20.0, min(20.0, track_error * 0.5))

                    # Track distance flown on outbound leg (use TAS for fixed ground track geometry)
                    half_spiral_outbound_flown += tas_fps * dt

                    # Transition to turn when outbound distance reached
                    if half_spiral_outbound_flown >= half_spiral_outbound_dist_needed:
                        # Calculate FINAL turn radius based on current geometry to ABEAM
                        # This is the actual cross-track distance at the start of the turn
                        abeam_point = GeoPoint(abeam_bucket.lat, abeam_bucket.lon)
                        bearing_to_abeam_now = calculate_initial_compass_bearing(cur_pos, abeam_point)
                        dist_to_abeam_now = geo_dist((lat, lon), (abeam_bucket.lat, abeam_bucket.lon)).feet
                        angle_off_now = abs(_angle_diff_deg(bearing_to_abeam_now, track))
                        cross_track_now = dist_to_abeam_now * math.sin(math.radians(min(90.0, angle_off_now)))

                        # Turn radius = cross-track / 2 (for 180° turn to reach ABEAM)
                        half_spiral_turn_radius = max(100.0, cross_track_now / 2.0)

                        half_spiral_phase = "turn"
                        half_spiral_turn_accumulated = 0.0

                elif half_spiral_phase == "turn":
                    # Execute 180° turn using FIXED radius calculated at turn start
                    # No dynamic recalculation - that causes S-curves

                    # Calculate bank angle for the fixed radius
                    # No minimum bank - could be a gentle 1° turn if winds are favorable
                    tan_bank = (tas_fps * tas_fps) / (G_FPS2 * half_spiral_turn_radius)
                    turn_bank_deg = math.degrees(math.atan(tan_bank))
                    turn_bank_deg = min(45.0, turn_bank_deg)  # Only cap at max, no minimum

                    # Turn direction
                    bank_target = opposite_spiral_direction * turn_bank_deg

                    # Track turn progress
                    if abs(bank_deg) > 0.1:  # Lower threshold for gentle turns
                        turn_rate = (G_FPS2 * math.tan(math.radians(abs(bank_deg)))) / max(1.0, tas_fps)
                        half_spiral_turn_accumulated += math.degrees(turn_rate * dt)

                    # Transition to inbound after full 180° turn
                    if half_spiral_turn_accumulated >= 180.0:
                        half_spiral_phase = "inbound"

                else:  # inbound
                    # Fly toward ABEAM bucket
                    angle_to_abeam = _angle_diff_deg(bearing_to_abeam, track)
                    bank_target = max(-25.0, min(25.0, angle_to_abeam * 0.5))

            # Check transition conditions to ABEAM bucket (applies to both phases)
            bearing_to_aircraft = calculate_initial_compass_bearing(
                GeoPoint(abeam_bucket.lat, abeam_bucket.lon), cur_pos
            )
            angle_diff = math.radians(_angle_diff_deg(bearing_to_aircraft, abeam_bucket.heading_deg))
            along_track_ft = dist_to_abeam * math.cos(angle_diff)
            cross_track_ft = abs(dist_to_abeam * math.sin(angle_diff))

            half_width = abeam_bucket.width_ft / 2
            half_depth = abeam_bucket.depth_ft / 2
            in_cross_track = cross_track_ft <= half_width
            in_along_track = abs(along_track_ft) <= half_depth
            in_altitude = abeam_bottom <= alt_agl <= abeam_top

            heading_diff_check = abs(_angle_diff_deg(track, abeam_bucket.heading_deg))
            heading_aligned = heading_diff_check <= abeam_bucket.heading_tol_deg

            # Transition to PO180 when we reach ABEAM bucket
            if in_cross_track and in_along_track and in_altitude and heading_aligned:
                in_opposite_spiral = False
                in_po180 = True
                po180_phase = "downwind"
                po180_downwind_flown = 0.0
                remaining_glide = alt_agl * straight_gr
                turn_radius = (tas_fps ** 2) / (G_FPS2 * math.tan(math.radians(30.0)))
                turn_arc = math.pi * turn_radius
                final_dist = pattern_offset_ft * 0.5
                po180_downwind_extension = max(0, remaining_glide - turn_arc - final_dist - 500)
                current_bucket_idx = len(buckets) - 1

            # Safety: transition after excessive turns
            if opposite_spiral_turns >= 5.0:
                in_opposite_spiral = False
                in_po180 = True
                po180_phase = "downwind"
                po180_downwind_flown = 0.0
                remaining_glide = alt_agl * straight_gr
                turn_radius = (tas_fps ** 2) / (G_FPS2 * math.tan(math.radians(30.0)))
                turn_arc = math.pi * turn_radius
                final_dist = pattern_offset_ft * 0.5
                po180_downwind_extension = max(0, remaining_glide - turn_arc - final_dist - 500)
                current_bucket_idx = len(buckets) - 1

        elif in_half_spiral:
            # Legacy half-spiral (kept for compatibility, but opposite_spiral should be used)
            in_half_spiral = False
            in_po180 = True
            po180_phase = "downwind"
            current_bucket_idx = len(buckets) - 1

        elif in_po180:
            dist_to_td = geo_dist((lat, lon), (touchdown_point.latitude, touchdown_point.longitude)).feet

            if po180_phase == "downwind":
                downwind_heading = _wrap_360(touchdown_heading + 180.0)
                track_error = _angle_diff_deg(downwind_heading, track)
                bank_target = max(-15.0, min(15.0, track_error * 0.4))

                xtrack_ft, along_ft = _cross_track_to_centerline_ft(
                    touchdown_point, cur_pos, touchdown_heading
                )
                distance_past_abeam = abs(along_ft)
                final_leg_if_turn_now = distance_past_abeam

                # Pick turn radius so the 180° arc displaces the aircraft
                # *exactly* from its current cross-track back to the
                # centerline. The abeam bucket is 2000 ft wide, so the
                # aircraft enters anywhere from pattern_offset±1000 ft
                # off CL; a fixed pattern_offset/2 radius leaves a
                # 200-1000 ft residual cross-track at touchdown. Floor
                # at the physical minimum-radius the aircraft can fly
                # at its 45° bank limit, so we don't ask for impossibly
                # tight turns when the aircraft was already near CL.
                min_phys_radius = (tas_fps * tas_fps) / (
                    G_FPS2 * math.tan(math.radians(45.0)))
                turn_radius_ft = max(
                    abs(xtrack_ft) / 2.0, min_phys_radius)
                turn_arc_ft = math.pi * turn_radius_ft
                # Save so the "turn" phase uses the same radius.
                po180_turn_radius = turn_radius_ft

                # Wind-correct the turn arc (average track is perpendicular to runway)
                if pattern_side == "left":
                    turn_avg_track = _wrap_360(touchdown_heading + 90.0)
                else:
                    turn_avg_track = _wrap_360(touchdown_heading - 90.0)
                turn_arc_wc = _wind_corrected_glide_distance(
                    turn_arc_ft, turn_avg_track, fps_to_knots(tas_fps), wind_dir, wind_speed
                )

                # Wind-correct the final leg (into wind - runway heading)
                final_leg_wc = _wind_corrected_glide_distance(
                    final_leg_if_turn_now, touchdown_heading, fps_to_knots(tas_fps), wind_dir, wind_speed
                )

                # The 180° turn is banked. Lift scales as 1/cos(bank) so
                # induced drag scales as 1/cos²(bank) — at the required
                # 1500 ft radius the bank is ~20°, costing ~12% of the
                # glide ratio. Treating the turn as straight-glide
                # underestimates altitude loss by ~80 ft for a typical
                # Decathlon-class arc, which translated to the aircraft
                # arriving 300-400 ft short of the threshold on final.
                required_bank_rad = math.atan(
                    (tas_fps * tas_fps) / (G_FPS2 * turn_radius_ft))
                required_bank_rad = max(
                    math.radians(15.0),
                    min(math.radians(45.0), required_bank_rad))
                gr_in_turn = max(
                    3.0, straight_gr * (math.cos(required_bank_rad) ** 2))

                # Final pads ~10% to absorb the cross-track intercept
                # corrections (the aircraft S-turns slightly on
                # centerline, not a perfect straight glide).
                final_leg_padded = final_leg_wc * 1.10

                required_altitude = (
                    (turn_arc_wc / gr_in_turn)
                    + (final_leg_padded / straight_gr))

                # Buffer absorbs the bank-roll-in / roll-out transient.
                # The GR correction above is the main fix; the buffer is
                # kept modest (75 ft) so we don't bias toward overshoot.
                turn_start_buffer_ft = 75

                # GATE: the 180° turn only ends back on the runway
                # centerline if the aircraft enters it actually heading
                # in the downwind direction. The spiral-exit tolerance
                # is 90° — way too loose — so the aircraft can drop
                # into the PO180 downwind phase still pointing nearly
                # perpendicular to the runway. Require heading within
                # ±20° of downwind before allowing the turn to start;
                # otherwise stay in downwind (correcting heading via
                # the bank_target above) and burn altitude until aligned.
                downwind_track_err = abs(_angle_diff_deg(
                    downwind_heading, track))
                aligned_for_turn = downwind_track_err <= 20.0

                if (aligned_for_turn
                        and alt_agl <= required_altitude
                            + turn_start_buffer_ft):
                    po180_phase = "turn"
                    po180_turn_accumulated = 0.0

            elif po180_phase == "turn":
                # Use the radius captured at turn-entry (sized to
                # current cross-track), not the fixed pattern_offset/2
                # — that's what guarantees the 180° turn ends on CL.
                required_radius_ft = (
                    po180_turn_radius if po180_turn_radius > 0
                    else pattern_offset_ft / 2.0)
                tan_bank = (tas_fps * tas_fps) / (G_FPS2 * required_radius_ft)
                calculated_bank_deg = math.degrees(math.atan(tan_bank))
                calculated_bank_deg = max(15.0, min(45.0, calculated_bank_deg))

                turn_sign = -1 if pattern_side == "left" else 1
                bank_target = turn_sign * calculated_bank_deg

                if abs(bank_deg) > 0.5:
                    turn_rate = (G_FPS2 * math.tan(math.radians(abs(bank_deg)))) / max(1.0, tas_fps)
                    po180_turn_accumulated += math.degrees(turn_rate * dt)

                if po180_turn_accumulated >= 175.0:
                    po180_phase = "final"

            else:
                # PO180 "final" phase — hold the runway centerline all
                # the way to touchdown using cross-track error to bias
                # the intercept angle. Earlier versions of this code
                # bailed to `in_po180 = False` at dist_to_td < 500 ft;
                # that handed control back to the generic "fly to bucket
                # center" path, which uses bearing-to-bucket instead of
                # runway-heading hold. The result was 30° bank locked
                # in for the last 10 seconds and a 65°-off arrival,
                # ~1700 ft short of the threshold. Keep centerline-hold
                # active until touchdown elevation is reached.
                xtrack_ft, along_ft = _cross_track_to_centerline_ft(
                    touchdown_point, cur_pos, touchdown_heading
                )

                # Tighten intercept as we get close so the aircraft
                # doesn't fly wide past the threshold. Scale the
                # intercept angle inversely with distance from TD.
                max_intercept_deg = 45.0
                intercept_angle = min(max_intercept_deg, abs(xtrack_ft) / 25.0)
                # Close-in tightening — within 1000 ft, scale intercept
                # down to a max of 15° so we land on heading, not
                # crab-bombing the centerline at 45°.
                if dist_to_td < 1000.0:
                    intercept_angle = min(intercept_angle, 15.0)
                if dist_to_td < 500.0:
                    intercept_angle = min(intercept_angle, 5.0)

                if abs(xtrack_ft) > 25:
                    if xtrack_ft > 0:
                        desired_track = _wrap_360(touchdown_heading - intercept_angle)
                    else:
                        desired_track = _wrap_360(touchdown_heading + intercept_angle)
                else:
                    desired_track = touchdown_heading

                track_error = _angle_diff_deg(desired_track, track)
                # Bank-limit tightens with proximity so we don't snap-
                # roll past the centerline in the last 500 ft.
                bank_limit = 20.0
                if dist_to_td < 500.0:
                    bank_limit = 10.0
                bank_target = max(-bank_limit,
                                   min(bank_limit, track_error * 0.4))

        else:
            if time_sec < reaction_end:
                bank_target = 0.0
            else:
                bearing_to_bucket = calculate_initial_compass_bearing(cur_pos, target_pos)
                dist_to_bucket_ft = geo_dist((lat, lon), (target_bucket.lat, target_bucket.lon)).feet
                entry_heading = target_bucket.heading_deg

                # Both SPIRAL and OPPOSITE_SPIRAL use alignment points
                # The alignment point is positioned behind the bucket (opposite of entry heading)
                # This ensures the aircraft approaches the bucket from the correct direction
                track_to_entry_diff = abs(_angle_diff_deg(entry_heading, track))

                if dist_to_bucket_ft > 3000 and track_to_entry_diff > target_bucket.heading_tol_deg:
                    align_dist_ft = min(10000.0, dist_to_bucket_ft * 0.75)
                    align_dist_nm = align_dist_ft / FT_PER_NM

                    # Alignment point is behind the bucket (opposite of entry heading)
                    alignment_point = point_from(target_pos, _wrap_360(entry_heading + 180), align_dist_nm)
                    desired_track = calculate_initial_compass_bearing(cur_pos, alignment_point)
                else:
                    desired_track = bearing_to_bucket

                # Calculate shortest turn direction
                track_error = _angle_diff_deg(desired_track, track)
                nav_bank_limit = 30.0
                bank_target = max(-nav_bank_limit, min(nav_bank_limit, track_error * 0.5))

        bank_alpha = min(1.0, dt / bank_tau_sec)
        bank_deg += (bank_target - bank_deg) * bank_alpha
        max_bank_used = max(max_bank_used, abs(bank_deg))

        if abs(bank_deg) > 0.5:
            turn_rate_rps = (G_FPS2 * math.tan(math.radians(abs(bank_deg)))) / max(1.0, tas_fps)
            turn_rate_dps = math.degrees(turn_rate_rps)
            turn_sign = 1.0 if bank_deg > 0 else -1.0
            track = _wrap_360(track + turn_sign * turn_rate_dps * dt)

        heading, gs_kt, drift_deg = _compute_wind_correction_angle(track, tas_fps, wn_fps, we_fps)
        gs_fps = gs_kt * 1.68781

        dist_to_target = geo_dist((lat, lon), (target_bucket.lat, target_bucket.lon)).feet

        if in_spiral:
            slip_intensity = 0.0
            effective_gr = straight_gr
        elif in_final_spiral:
            # No slip during final spiral - spiral is the altitude management
            slip_intensity = 0.0
            effective_gr = straight_gr
        elif in_opposite_spiral and opposite_spiral_phase == "full_spiral":
            # No slip during full 360° spirals - spiral geometry must handle altitude loss
            slip_intensity = 0.0
            effective_gr = straight_gr
        elif in_po180 and po180_phase != "final":
            slip_intensity = 0.0
            effective_gr = straight_gr
        elif in_po180 and po180_phase == "final":
            # Wind-correct the distance for slip calculation
            # On final, track is roughly touchdown_heading
            dist_to_td_wind_corrected = _wind_corrected_glide_distance(
                dist_to_target, touchdown_heading, fps_to_knots(tas_fps), wind_dir, wind_speed
            )
            slip_intensity, effective_gr = _calculate_slip_for_bucket(
                alt_agl, dist_to_td_wind_corrected, target_bucket.altitude_ft, straight_gr
            )
        else:
            abeam_bkt = None
            for b in buckets:
                if b.name == "ABEAM":
                    abeam_bkt = b
                    break

            if abeam_bkt:
                dist_to_abeam = geo_dist((lat, lon), (abeam_bkt.lat, abeam_bkt.lon)).feet
                abeam_top = abeam_bkt.altitude_ft + abeam_bkt.height_ft / 2

                # Wind-correct distance for consistent ground track model
                bearing_to_abeam = calculate_initial_compass_bearing(
                    cur_pos, GeoPoint(abeam_bkt.lat, abeam_bkt.lon)
                )
                dist_to_abeam_wc = _wind_corrected_glide_distance(
                    dist_to_abeam, bearing_to_abeam, fps_to_knots(tas_fps), wind_dir, wind_speed
                )

                arrival_alt_no_slip = alt_agl - (dist_to_abeam_wc / straight_gr)
                min_gr_with_slip = straight_gr * 0.6
                arrival_alt_max_slip = alt_agl - (dist_to_abeam_wc / min_gr_with_slip)

                if arrival_alt_no_slip <= abeam_top:
                    slip_intensity = 0.0
                    effective_gr = straight_gr
                elif arrival_alt_max_slip <= abeam_top:
                    slip_intensity, effective_gr = _calculate_slip_for_bucket(
                        alt_agl, dist_to_abeam_wc, abeam_bkt.altitude_ft, straight_gr
                    )
                else:
                    slip_intensity = 0.0
                    effective_gr = straight_gr
            else:
                # Wind-correct distance to target bucket
                bearing_to_target = calculate_initial_compass_bearing(cur_pos, target_pos)
                dist_to_target_wc = _wind_corrected_glide_distance(
                    dist_to_target, bearing_to_target, fps_to_knots(tas_fps), wind_dir, wind_speed
                )
                slip_intensity, effective_gr = _calculate_slip_for_bucket(
                    alt_agl, dist_to_target_wc, target_bucket.altitude_ft, straight_gr
                )

        if abs(bank_deg) > 0.5:
            n_load = compute_load_factor(abs(bank_deg))
            effective_gr = effective_gr / max(n_load, 1.0)
        effective_gr = max(2.0, effective_gr)

        slip_pct = round(slip_intensity * 100, 0)
        max_slip_used = max(max_slip_used, slip_pct)

        # Fixed ground distance step (ground track is predetermined geometry)
        # Use TAS-based reference distance for consistent path sampling
        ds_ground_ft = tas_fps * dt

        # Variable timestep based on groundspeed (how long to cover that ground distance)
        actual_dt = ds_ground_ft / gs_fps if gs_fps > 1.0 else dt

        # Altitude loss based on actual time in the air
        vs_fps = tas_fps / effective_gr
        alt_agl = max(0.0, alt_agl - vs_fps * actual_dt)
        vs_fpm = vs_fps * 60.0

        # Position update uses fixed ground distance (not wind-affected)
        dist_nm = ds_ground_ft / FT_PER_NM
        new_pos = point_from(cur_pos, track, dist_nm)
        lat = new_pos.latitude
        lon = new_pos.longitude

        time_sec += actual_dt

        path.append([lat, lon])

        hover_data.append({
            "time": round(time_sec, 2),
            "phase": phase_name,
            "alt": round(alt_agl, 1),
            "ias": round(ias, 1),
            "tas": round(tas_knots, 1),
            "gs": round(gs_kt, 1),
            "heading": round(heading, 1),
            "track": round(track, 1),
            "aob": round(bank_deg, 1),
            "drift": round(drift_deg, 1),
            "vs": round(-vs_fpm, 0),
            "slip_pct": slip_pct,
            "glide_ratio": round(effective_gr, 1),
            "load_factor": ((1.0 / math.cos(math.radians(bank_deg))) if abs(bank_deg) < 89.9 else None),
            "segment": phase_name,
        })

        if time_sec > MAX_SIM_TIME_SEC:
            break

    # Success = "landed on the runway, on heading." The old check was just
    # straight-line distance from TD < 400 ft + alt < 100 ft, which let
    # off-heading splats next to the threshold count as success (e.g.
    # final heading 54° off runway) and rejected on-centerline overshoots
    # by 100 ft. Rewrite in runway-relative coordinates: the touchdown
    # zone is a rectangle along the runway extending from slightly short
    # of the threshold to ~1500 ft past, runway-width-wide, with the
    # aircraft heading within ±15° of the runway.
    final_bucket = buckets[-1] if buckets else None
    success = False
    if final_bucket and final_bucket.name == "TOUCHDOWN" and hover_data:
        end_pt = GeoPoint(lat, lon)
        td_pt = GeoPoint(final_bucket.lat, final_bucket.lon)
        xtrack_ft, along_ft = _cross_track_to_centerline_ft(
            td_pt, end_pt, touchdown_heading)
        end_heading = hover_data[-1].get("heading", 0.0)
        hdg_err = abs(_angle_diff_deg(end_heading, touchdown_heading))

        # Sign convention from _cross_track_to_centerline_ft: along > 0
        # means the aircraft is *past* TD in the landing direction —
        # i.e. on the rolling-out portion of the runway, which is
        # exactly where you want to touch down. along < 0 means short
        # of the threshold (still on approach). Accept up to ~250 ft
        # short of threshold (high-flare margin near the numbers) and
        # up to ~1500 ft past (the usable landing zone of a typical
        # 3000-5000 ft runway).
        # Engine-out emergency landings aren't a checkride straight-in.
        # The pilot's job is to put the airplane on the runway alive — if
        # the touchdown is within ±45° of runway heading (a common sideways
        # crab/turning-final scenario) and within ~150 ft of centerline (a
        # 300 ft wide landing area covers most paved runways plus the
        # immediate overrun), call it a save. The pilot can absorb the
        # remaining misalignment with rudder/brake on the rollout.
        on_runway_along = -250.0 <= along_ft <= 1500.0
        on_runway_cross = abs(xtrack_ft) <= 150.0
        aligned = hdg_err <= 45.0
        low_enough = alt_agl < BUCKET_TOUCHDOWN_HEIGHT
        success = on_runway_along and on_runway_cross and aligned and low_enough

    if success:
        reason = "touchdown"
    elif alt_agl <= 0:
        reason = "impact_short"
    else:
        reason = "timeout"

    metadata = {
        "success": success,
        "reason": reason,
        "impact_point": (lat, lon) if not success and alt_agl <= 0 else None,
        "turn_direction": "left" if pattern_side == "left" else "right",
        "phase_times": phase_times,
        "total_time_sec": time_sec,
        "average_glide_ratio": straight_gr,
        "min_speed_margin_kt": 0.0,
        "max_bank_used_deg": max_bank_used,
        "final_phase": hover_data[-1]["phase"] if hover_data else "unknown",
        "best_glide_kias": best_glide_kias,
        "straight_glide_ratio": straight_gr,
        "slip_used": max_slip_used > 0,
        "slip_intensity_pct": max_slip_used,
        "initial_strategy": "bucket_based",
        "final_strategy": "bucket_based",
        "initial_position_type": buckets[0].name if buckets else "unknown",
        "pattern_side": pattern_side,
        "spiral_turns_completed": spiral_turns,
        "half_spiral_turns_completed": half_spiral_turns,
        "final_spiral_turns_completed": final_spiral_turns,
        "used_opposite_spiral": use_opposite_spiral,
        "used_final_spiral": any(b.name == "FINAL_SPIRAL" for b in buckets),
        "bucket_chain": [b.name for b in buckets],
        # Phase H — surface the live winds-aloft layers used (empty
        # when the static sidebar wind was used) so the results modal
        # can show the column the sim consumed.
        "wind_layers_used": wind_layers_used,
        "wind_dir_effective_deg": float(wind_dir),
        "wind_speed_effective_kt": float(wind_speed),
    }

    return path, hover_data, metadata


# Alias for backwards compatibility
simulate_engineout_glide = run_simulation


def find_minimum_altitude(
    start_point: GeoPoint,
    start_heading: float,
    touchdown_point: GeoPoint,
    touchdown_heading: float,
    ac: dict,
    engine_option: str,
    weight_lbs: float,
    flap_config: str,
    prop_config: str,
    oat_c: float,
    altimeter_inhg: float,
    wind_dir: float,
    wind_speed: float,
    touchdown_elev_ft: float = 0.0,
    max_bank_deg: float = 45.0,
    reaction_sec: float = DEFAULT_REACTION_SEC,
    alt_low: float = 100.0,
    alt_high: float = 5000.0,
    resolution: float = 25.0,
    pattern_offset_ft: float = DEFAULT_PATTERN_OFFSET_FT,
    pattern_altitude_ft: float = DEFAULT_PATTERN_ALTITUDE_FT,
) -> Tuple[float, List[List[float]], List[Dict[str, Any]], Dict[str, Any]]:
    """
    Find minimum altitude needed for successful engine-out landing using binary search.

    Returns: (min_altitude, path, hover_data, metadata) from the successful simulation.
    """
    best_success_alt = None
    best_path = []
    best_hover = []
    best_meta = {}

    # Binary search for minimum altitude
    low = alt_low
    high = alt_high

    while high - low > resolution:
        mid = (low + high) / 2.0

        try:
            path, hover_data, metadata = run_simulation(
                start_point=start_point,
                start_heading=start_heading,
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
                altitude_agl=mid,
                touchdown_elev_ft=touchdown_elev_ft,
                max_bank_deg=max_bank_deg,
                pattern_offset_ft=pattern_offset_ft,
                pattern_altitude_ft=pattern_altitude_ft,
                reaction_sec=reaction_sec,
            )

            if metadata.get("success", False):
                best_success_alt = mid
                best_path = path
                best_hover = hover_data
                best_meta = metadata
                high = mid
            else:
                low = mid
        except Exception:
            low = mid

    # If no success found, return the high altitude attempt
    if best_success_alt is None:
        try:
            path, hover_data, metadata = run_simulation(
                start_point=start_point,
                start_heading=start_heading,
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
                altitude_agl=alt_high,
                touchdown_elev_ft=touchdown_elev_ft,
                max_bank_deg=max_bank_deg,
                pattern_offset_ft=pattern_offset_ft,
                pattern_altitude_ft=pattern_altitude_ft,
                reaction_sec=reaction_sec,
            )
            return alt_high, path, hover_data, metadata
        except Exception:
            return alt_high, [], [], {"success": False, "reason": "simulation_error"}

    return best_success_alt, best_path, best_hover, best_meta


def compute_glide_envelope(
    start_point: GeoPoint,
    altitude_ft: float,
    glide_ratio: float,
    wind_dir: float,
    wind_speed: float,
    tas_knots: float,
    num_points: int = 36,
    wind_profile=None,
    start_elev_ft: float = 0.0,
    elevation_fn=None,
    terrain_buffer_ft: float = 200.0,
    terrain_step_nm: float = 0.5,
) -> List[List[float]]:
    """
    Compute the glide envelope (reachable area) from a given position.

    Wind-aware: the envelope is NOT a circle. It's elongated downwind
    (can glide farther with tailwind) and compressed upwind (headwind
    reduces ground distance covered).

    If `wind_profile` is provided, the envelope integrates per-altitude-
    band using winds at each MSL altitude — significantly more accurate
    than a single mean wind when there's vertical shear (e.g. 5 kt at
    surface vs 25 kt at 9000 ft). Without wind_profile the function
    falls back to the old single-wind model (uses wind_dir/wind_speed).

    Args:
        start_point: Starting position (GeoPoint)
        altitude_ft: Altitude AGL in feet at the start
        glide_ratio: Aircraft glide ratio (e.g., 9.0)
        wind_dir: Wind FROM direction in degrees (TRUE). Used as the
                  single-wind fallback when wind_profile is None.
        wind_speed: Wind speed in knots (TRUE). Fallback.
        tas_knots: True airspeed in knots
        num_points: Number of points around the envelope
        wind_profile: Optional core.winds_aloft.WindProfile. When
                      provided, integrate the descent in 500-ft bands.
        start_elev_ft: Field elevation in MSL feet so wind_profile
                       lookups use the right MSL altitude.

    Returns:
        List of [lat, lon] points forming the envelope polygon
    """
    if altitude_ft <= 0 or glide_ratio <= 0 or tas_knots <= 0:
        return []

    tas_fps = tas_knots * 1.68781
    sink_rate_fps = tas_fps / glide_ratio

    # Single-wind fallback path. Compact + matches pre-Phase-I2 behavior
    # when no WindProfile is staged (e.g. user hasn't picked an airport
    # with live winds aloft).
    def _single_wind_endpoint(bearing_deg: float, wd: float, ws: float):
        wind_to_rad = math.radians((wd + 180.0) % 360.0)
        wind_north_kt = ws * math.cos(wind_to_rad)
        wind_east_kt = ws * math.sin(wind_to_rad)
        bearing_rad = math.radians(bearing_deg)
        tas_north_kt = tas_knots * math.cos(bearing_rad)
        tas_east_kt = tas_knots * math.sin(bearing_rad)
        gs_north_kt = tas_north_kt + wind_north_kt
        gs_east_kt = tas_east_kt + wind_east_kt
        gs_knots = math.sqrt(gs_north_kt**2 + gs_east_kt**2)
        glide_time_sec = altitude_ft / sink_rate_fps
        ground_distance_nm = (gs_knots * glide_time_sec) / 3600.0
        if gs_knots > 0.1:
            track_deg = math.degrees(
                math.atan2(gs_east_kt, gs_north_kt)) % 360.0
        else:
            track_deg = bearing_deg
        return point_from(start_point, track_deg, ground_distance_nm)

    # Wind-profile path: integrate descent in altitude bands and
    # accumulate displacement at each one's wind. Within a single
    # bearing (chosen heading the pilot picks), the aircraft holds
    # that heading while wind drifts the path. Each band contributes
    # GS_band × t_band of along-bearing + crosswind displacement.
    def _profile_endpoint(bearing_deg: float):
        bearing_rad = math.radians(bearing_deg)
        tas_north_kt = tas_knots * math.cos(bearing_rad)
        tas_east_kt = tas_knots * math.sin(bearing_rad)
        north_disp_ft = 0.0
        east_disp_ft = 0.0
        alt_remaining = altitude_ft
        BAND = 500.0  # ft — coarse enough to be cheap, fine enough
                     # to track the 1500/3000/6000/9000/12000-ft layer
                     # transitions in the Open-Meteo column.
        while alt_remaining > 1e-3:
            band_size = min(BAND, alt_remaining)
            band_mid_agl = alt_remaining - band_size / 2.0
            band_mid_msl = start_elev_ft + band_mid_agl
            try:
                wd, ws = wind_profile.at(band_mid_msl)
            except Exception:
                wd, ws = float(wind_dir), float(wind_speed)
            wind_to_rad = math.radians((float(wd) + 180.0) % 360.0)
            wind_north_kt = float(ws) * math.cos(wind_to_rad)
            wind_east_kt = float(ws) * math.sin(wind_to_rad)
            gs_north_kt = tas_north_kt + wind_north_kt
            gs_east_kt = tas_east_kt + wind_east_kt
            descent_time_sec = band_size / sink_rate_fps
            north_disp_ft += gs_north_kt * 1.68781 * descent_time_sec
            east_disp_ft += gs_east_kt * 1.68781 * descent_time_sec
            alt_remaining -= band_size
        total_disp_ft = math.sqrt(north_disp_ft**2 + east_disp_ft**2)
        if total_disp_ft < 1e-3:
            return start_point
        track_deg = math.degrees(
            math.atan2(east_disp_ft, north_disp_ft)) % 360.0
        return point_from(start_point, track_deg, total_disp_ft / FT_PER_NM)

    # Terrain-aware clipping. For each bearing, walk outward in
    # terrain_step_nm chunks tracking remaining altitude after descent
    # at that range. Stop when MSL altitude drops below local terrain
    # plus the buffer; return the last safe point instead of the
    # raw wind-distance endpoint. Pure no-terrain path falls through
    # to the original wind-only behavior.
    def _terrain_clip(end_pt: GeoPoint, bearing_deg: float) -> GeoPoint:
        if elevation_fn is None:
            return end_pt
        # Un-clipped reach as ground distance from start → end_pt.
        d_nm = geo_dist((start_point.latitude, start_point.longitude),
                         (end_pt.latitude, end_pt.longitude)).nm
        if d_nm <= terrain_step_nm:
            return end_pt
        # MSL altitude at start
        start_msl = start_elev_ft + altitude_ft
        last_safe = start_point
        # Linear descent: assume constant glide angle along this radial
        # — for envelope visualization this is fine; per-band wind
        # already shaped the endpoint distance.
        n_steps = max(1, int(math.ceil(d_nm / terrain_step_nm)))
        for k in range(1, n_steps + 1):
            frac = k / n_steps
            d_here = d_nm * frac
            test_pt = point_from(start_point, bearing_deg, d_here)
            alt_msl_here = start_msl - frac * altitude_ft
            try:
                terrain_m = elevation_fn(test_pt.latitude, test_pt.longitude)
            except Exception:
                terrain_m = None
            if terrain_m is None or terrain_m != terrain_m:  # NaN check
                last_safe = test_pt
                continue
            terrain_ft = terrain_m * 3.28084
            if alt_msl_here < terrain_ft + terrain_buffer_ft:
                return last_safe
            last_safe = test_pt
        return last_safe

    use_profile = wind_profile is not None
    envelope = []
    bearing_step = 360.0 / num_points
    for i in range(num_points):
        b = i * bearing_step
        raw_pt = (_profile_endpoint(b) if use_profile
                  else _single_wind_endpoint(b, wind_dir, wind_speed))
        # Per-bearing terrain clip (no-op when elevation_fn is None).
        pt = _terrain_clip(raw_pt, b)
        envelope.append([pt.latitude, pt.longitude])
    if envelope:
        envelope.append(envelope[0])
    return envelope
