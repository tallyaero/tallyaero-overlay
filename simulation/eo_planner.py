"""Engine-out glide-path planner — backward construction from touchdown.

Replaces the legacy bucket-chain + state-machine approach with a closed-form
geometric planner that builds the full trajectory before the simulator
"flies" any of it. The simulator becomes a follow-the-plan executor instead
of a reactive controller — so the path is deterministic, inspectable, and
free of the transitions/edge-cases that plagued the old design.

Anchored in FAA-authoritative procedure, not magic numbers:

  Reference altitudes (AGL):
    HIGH_KEY = 1500   over the touchdown — the "high gate" before pattern
                       (AOPA "Bundle of Energy"; high-key/low-key training)
    LOW_KEY  = 1000   abeam touchdown on downwind = pattern altitude
                       (AFH Ch. 8 traffic patterns; AOPA practice guidance)
    COMMIT   =  400   below this: no turns, land straight ahead
                       (FAA-P-8740-44 "Impossible Turn")

  Reference bank:
    MAX_BANK      = 45°  absolute limit (FAA-P-8740-44)
    PLANNING_BANK = 35°  default planner bank — leaves margin

  Reference ACS tolerance (Commercial 180° Power-Off Accuracy Landing):
    Touchdown at or beyond the designated point, ≤200 ft past
    (FAA-S-ACS-7B Commercial Pilot ACS)

The planner walks backward from the touchdown point:

    touchdown ← short_final ← base→final_arc ← LOW_KEY ← optional_downwind
                              ← optional_HIGH_KEY_spiral ← entry_vector ← start

Each connection between key points is one trajectory segment with a clear
geometric type (straight / turn / spiral) and a closed-form alt cost.

The output is a `GlidePlan`: an ordered list of `GlideSegment`s plus a
`GlideDiagnostics` block the results popup uses to explain "what would
need to be true for this glide to work."
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from geopy import Point as GeoPoint
from geopy.distance import geodesic as geo_dist


# =============================================================================
# Pinned reference values (FAA / AOPA / FAA-P-8740-44)
# =============================================================================

HIGH_KEY_AGL_FT = 1500.0    # retained for diagnostics/legacy refs
LOW_KEY_AGL_FT  = 1000.0    # retained for diagnostics/legacy refs
COMMIT_AGL_FT   =  400.0

MAX_BANK_DEG       = 45.0   # absolute physical limit per FAA-P-8740-44
PLANNING_BANK_DEG  = 30.0   # default planner bank (visible pattern turns)

# Traffic-pattern geometry — sized so legs are visible on the map at typical
# zoom levels (~0.5 NM features). The pattern uses TWO turn radii:
#   • R_normal — small (computed from planning_bank ~30°), used for the
#     initial join turn and the downwind-join smoothing turn.
#   • R_po180 — large (= PATTERN_OFFSET_FT / 2 for the PO180 to close), used
#     for the continuous base→final 180° arc. The bank for this is derived
#     from the TAS and the radius — typically shallow (~13-20°), which is
#     fine because engine-out PO180 is a conservative maneuver, not a max-
#     performance turn.
PATTERN_OFFSET_FT   = 4000.0   # downwind offset from runway centerline (~0.66 NM)
FINAL_LEG_FT        = 1500.0   # default short-final length (~0.25 NM). Kept
                                # small so the trajectory absorbs excess via
                                # SPIRAL (tightest 30°, widest 1/2 standard
                                # rate) before resorting to lengthening the
                                # downwind/final legs.
MAX_EXTENSION_FT    = 6000.0   # downwind extension cap (~1 NM); beyond this we
                                # switch to an overhead orbit to stay near the
                                # field per FAA engine-out guidance.
SHORT_FINAL_DIST_NM = FINAL_LEG_FT / 6076.115
SHORT_FINAL_AGL_FT  = 100.0    # alt at the touchdown-1 sample point
GLIDE_ANGLE_DEG     = 3.0      # nominal glide angle on short final

# Overhead orbit (used when extension would exceed MAX_EXTENSION_FT). Radius
# is picked for map visibility — at 73 KTAS this is ~25° of bank.
ORBIT_RADIUS_FT     = 1800.0   # 0.30 NM — visible at typical zoom (legacy default)
ORBIT_TARGET_AGL_FT = 1500.0   # exit altitude (transitions to downwind entry)
ORBIT_MIN_TURNS     = 0.5      # at least a half orbit if we trigger it
ORBIT_MAX_TURNS     = 8.0

# Spiral radius range — tightest at 30° AOB, widest at 1/2 standard rate
# (1.5°/sec). The planner scales the spiral radius with the altitude
# excess so a single sweeping turn absorbs most of the energy.
SPIRAL_BANK_MAX_DEG       = 30.0      # tightest spiral
SPIRAL_RATE_MIN_DEG_PER_S = 1.5       # widest spiral (1/2 standard rate)

# Straight-in fallback alignment thresholds — when the start is behind the
# threshold, aligned, and within the cross-track tolerance, the planner skips
# the lateral pattern.
STRAIGHT_IN_MAX_XTRACK_FT     = 2000.0
STRAIGHT_IN_MAX_HEADING_DIFF  = 45.0

FT_PER_NM = 6076.115
G_FPS2    = 32.174

# Slip on final: when the aircraft arrives at the final fix with excess
# altitude, the pilot can slip to increase sink rate over the final leg.
# Effective glide ratio during slip is GR × SLIP_GR_MIN_FACTOR, capping
# the absorbable excess at (final_leg × (1/factor − 1) / GR). For
# FINAL_LEG_FT = 1500 and GR = 9 this gives ~333 ft of slip capacity.
SLIP_GR_MIN_FACTOR = 1.0 / 3.0


# =============================================================================
# Data structures
# =============================================================================

@dataclass
class GlideSegment:
    """One geometric piece of the planned trajectory.

    kind values:
      "straight" — great-circle glide from start → end at constant heading
      "turn"     — constant-radius arc of `turn_angle_deg` (signed: +=CW)
      "spiral"   — N orbits at a fixed point at constant bank
    """
    kind: str
    start_lat: float
    start_lon: float
    start_alt_agl_ft: float
    start_heading_deg: float
    end_lat: float
    end_lon: float
    end_alt_agl_ft: float
    end_heading_deg: float

    # Optional: turns + spirals only
    center_lat: Optional[float] = None
    center_lon: Optional[float] = None
    turn_radius_ft: Optional[float] = None
    turn_angle_deg: Optional[float] = None     # signed; for "turn"
    spiral_turns: Optional[float] = None       # for "spiral"
    spiral_bank_deg: Optional[float] = None    # for "spiral"
    spiral_direction: Optional[str] = None     # "left"/"right" for "spiral"

    # Filled in by helper:
    ground_distance_ft: float = 0.0
    label: str = ""


@dataclass
class KeyPosition:
    """A named position the plan threads through (used by the results popup
    and the side-view chart)."""
    name: str
    lat: float
    lon: float
    alt_agl_ft: float
    heading_deg: float


@dataclass
class GlideDiagnostics:
    """Everything the results popup wants to display."""
    # Energy state at start
    start_alt_msl_ft: float
    start_alt_agl_ft: float
    direct_dist_nm: float
    direct_glide_alt_ft: float           # alt cost flying direct
    arrival_alt_agl_ft: float            # remaining AGL over field if direct

    # Key-position checks
    excess_at_high_key_ft: float
    excess_at_low_key_ft: float

    # Plan choice
    approach_strategy: str               # "high_key", "low_key_direct",
                                          # "straight_in", "off_field"
    pattern_side: str                    # "left" or "right"
    on_final_side: bool

    # Aircraft
    best_glide_tas_kt: float
    glide_ratio: float
    planning_bank_deg: float
    max_bank_deg: float
    turn_radius_ft: float

    # Spiral (zero if not used)
    spiral_turns: float
    spiral_bank_deg: float

    # Retrospective — what would have made this glide work
    required_alt_agl_to_make_it_ft: float
    required_max_dist_nm: float

    # Wind
    wind_dir_deg: float
    wind_speed_kt: float
    final_wind_component_kt: float       # + = headwind, - = tailwind

    # Outcome
    feasible: bool
    failure_reason: Optional[str]


@dataclass
class GlidePlan:
    """The output of `plan_glide`. Pass to the executor to integrate it."""
    segments: list[GlideSegment]
    key_positions: list[KeyPosition]
    diagnostics: GlideDiagnostics


# =============================================================================
# Geometry helpers
# =============================================================================

def _wrap_360(angle: float) -> float:
    return angle % 360.0


def _angle_diff_deg(a: float, b: float) -> float:
    """Signed shortest-arc difference (a − b), result in (−180, 180]."""
    d = (a - b + 540.0) % 360.0 - 180.0
    return d


def _bearing(p1: GeoPoint, p2: GeoPoint) -> float:
    """Initial bearing from p1 to p2 in true degrees."""
    lat1 = math.radians(p1.latitude)
    lat2 = math.radians(p2.latitude)
    dlon = math.radians(p2.longitude - p1.longitude)
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return _wrap_360(math.degrees(math.atan2(y, x)))


def _point_at_bearing(origin: GeoPoint, bearing_deg: float,
                        distance_ft: float) -> GeoPoint:
    """Offset a point by (bearing, distance in ft)."""
    from geopy.distance import distance
    return distance(feet=distance_ft).destination(origin, bearing_deg)


def _ft(p1: GeoPoint, p2: GeoPoint) -> float:
    return geo_dist((p1.latitude, p1.longitude),
                     (p2.latitude, p2.longitude)).feet


def _turn_radius_ft(tas_kt: float, bank_deg: float) -> float:
    """Coordinated-turn radius at TAS (kt) and bank (deg)."""
    tas_fps = max(1.0, tas_kt * 1.68781)
    bank_rad = math.radians(max(1.0, min(60.0, bank_deg)))
    return (tas_fps ** 2) / (G_FPS2 * math.tan(bank_rad))


def _cross_track_along_track_ft(touchdown: GeoPoint, position: GeoPoint,
                                  runway_heading: float) -> tuple[float, float]:
    """Decompose `position` − `touchdown` into along-track (positive in
    runway-heading direction) and cross-track (positive to right looking
    along runway heading) components, in feet.
    """
    dist_ft = _ft(touchdown, position)
    if dist_ft < 1e-6:
        return 0.0, 0.0
    bearing_td_to_pos = _bearing(touchdown, position)
    angle = math.radians(_angle_diff_deg(bearing_td_to_pos, runway_heading))
    along_ft = dist_ft * math.cos(angle)
    cross_ft = dist_ft * math.sin(angle)
    return cross_ft, along_ft


def _wind_corrected_alt_cost_ft(ground_dist_ft: float, track_deg: float,
                                  tas_kt: float, glide_ratio: float,
                                  wind_dir_deg: float, wind_speed_kt: float) -> float:
    """Altitude required to cover `ground_dist_ft` along bearing `track_deg`
    at TAS through wind. Headwind costs more altitude per foot of ground;
    tailwind costs less. Uses the headwind/tailwind component along the
    track — adequate for planning (executor handles per-segment drift)."""
    if ground_dist_ft <= 0 or glide_ratio <= 0 or tas_kt <= 0:
        return 0.0
    headwind_kt = wind_speed_kt * math.cos(
        math.radians(_angle_diff_deg(wind_dir_deg, track_deg)))
    gs_kt = max(0.1, tas_kt - headwind_kt)
    # alt_cost = ground_dist / glide_ratio_over_ground
    # glide_ratio_over_ground = (TAS / GS) × glide_ratio_through_air
    return ground_dist_ft / (gs_kt / tas_kt * glide_ratio)


# =============================================================================
# Backward-construction key positions
# =============================================================================

def _final_entry(touchdown: GeoPoint, runway_heading: float
                  ) -> tuple[GeoPoint, float]:
    """End of short final = entry to the final segment, SHORT_FINAL_DIST_NM
    behind touchdown on the runway centerline. Returns (position, agl)."""
    reverse_bearing = _wrap_360(runway_heading + 180.0)
    pos = _point_at_bearing(touchdown, reverse_bearing,
                              SHORT_FINAL_DIST_NM * FT_PER_NM)
    return pos, SHORT_FINAL_AGL_FT


def _low_key(touchdown: GeoPoint, runway_heading: float,
              pattern_side: str, turn_radius_ft: float
              ) -> tuple[GeoPoint, float]:
    """Low Key = abeam touchdown on downwind, 2 × turn_radius off centerline
    (so a 180° turn from this point at the planning bank ends precisely on
    short final). Returns (position, AGL)."""
    if pattern_side == "left":
        perp = _wrap_360(runway_heading - 90.0)
    else:
        perp = _wrap_360(runway_heading + 90.0)
    pos = _point_at_bearing(touchdown, perp, 2.0 * turn_radius_ft)
    return pos, LOW_KEY_AGL_FT


def _high_key(touchdown: GeoPoint) -> tuple[GeoPoint, float]:
    """High Key = directly over the touchdown at 1500 AGL."""
    return touchdown, HIGH_KEY_AGL_FT


# =============================================================================
# Strategy decision
# =============================================================================

def _choose_strategy(*, arrival_alt_agl: float,
                       excess_at_low_key: float,
                       excess_at_high_key: float,
                       on_final_side: bool,
                       cross_track_ft: float,
                       heading_diff_deg: float) -> str:
    """Pick one of:
       "off_field"       — can't make it
       "straight_in"     — final side, aligned, energy tight
       "high_key"        — significant excess; spiral overhead
       "low_key_direct"  — modest excess; fly direct to low key, PO180

    Decision logic mirrors what a real instructor would teach (see Pilot
    Institute "Deadstick Landings", AOPA "Bundle of Energy"):

    1. If we won't reach the field at all → off_field
    2. If we're on the final side AND aligned AND tight → straight_in
       (don't waste altitude on a lateral pattern when a clean straight-in
       works)
    3. If we have ≥500 ft of excess over HIGH_KEY → high_key
       (the standard "above pattern altitude, stay over the field" play)
    4. Otherwise → low_key_direct (normal PO180 entry)"""
    if arrival_alt_agl < 0:
        return "off_field"

    if (on_final_side
            and abs(heading_diff_deg) <= STRAIGHT_IN_MAX_HEADING_DIFF
            and abs(cross_track_ft) <= STRAIGHT_IN_MAX_XTRACK_FT
            and excess_at_low_key <= 500):
        return "straight_in"

    if excess_at_high_key >= 500:
        return "high_key"

    return "low_key_direct"


# =============================================================================
# Segment constructors
# =============================================================================

def _straight_segment(start: GeoPoint, start_alt: float,
                       end: GeoPoint, end_alt: float,
                       label: str = "") -> GlideSegment:
    ground_dist = _ft(start, end)
    heading = _bearing(start, end) if ground_dist > 1e-6 else 0.0
    return GlideSegment(
        kind="straight",
        start_lat=start.latitude, start_lon=start.longitude,
        start_alt_agl_ft=start_alt, start_heading_deg=heading,
        end_lat=end.latitude, end_lon=end.longitude,
        end_alt_agl_ft=end_alt, end_heading_deg=heading,
        ground_distance_ft=ground_dist,
        label=label,
    )


def _turn_segment_180(start: GeoPoint, start_alt: float,
                       start_heading: float, end: GeoPoint, end_alt: float,
                       end_heading: float, turn_radius_ft: float,
                       direction: str, label: str = "") -> GlideSegment:
    """180° base→final arc. `direction` is "left" or "right" (CCW / CW).
    Arc length = π × R."""
    arc_length_ft = math.pi * turn_radius_ft
    sign = -1.0 if direction == "left" else 1.0
    # Center is perpendicular to start_heading by `direction` at distance R.
    center_bearing = _wrap_360(start_heading + sign * 90.0)
    center = _point_at_bearing(start, center_bearing, turn_radius_ft)
    return GlideSegment(
        kind="turn",
        start_lat=start.latitude, start_lon=start.longitude,
        start_alt_agl_ft=start_alt, start_heading_deg=start_heading,
        end_lat=end.latitude, end_lon=end.longitude,
        end_alt_agl_ft=end_alt, end_heading_deg=end_heading,
        center_lat=center.latitude, center_lon=center.longitude,
        turn_radius_ft=turn_radius_ft,
        turn_angle_deg=sign * 180.0,
        ground_distance_ft=arc_length_ft,
        label=label,
    )


def _turn_segment_n(*, start: GeoPoint, start_alt: float, start_heading: float,
                       turn_angle_deg: float, turn_radius_ft: float,
                       direction: str, end_alt: float,
                       label: str = "") -> GlideSegment:
    """General N-degree coordinated turn at constant radius. `direction` is
    "left" (CCW) or "right" (CW); `turn_angle_deg` is the positive sweep
    (e.g., 90 for a quarter turn). End position is computed from the start
    + heading + radius geometry."""
    sign = +1.0 if direction == "right" else -1.0
    # Center is perpendicular to start_heading on the side of the turn.
    # Right (CW) turn: center bearing = H + 90°. Left (CCW): H − 90°.
    center_bearing = _wrap_360(start_heading + sign * 90.0)
    center = _point_at_bearing(start, center_bearing, turn_radius_ft)
    # Radial bearing from center to start is opposite of center bearing.
    radial_at_start = _wrap_360(center_bearing + 180.0)
    # CW turn → compass bearing increases; CCW turn → decreases.
    radial_at_end = _wrap_360(radial_at_start + sign * abs(turn_angle_deg))
    end_pos = _point_at_bearing(center, radial_at_end, turn_radius_ft)
    # End heading = start_heading rotated by sign × angle.
    end_heading = _wrap_360(start_heading + sign * abs(turn_angle_deg))
    arc_length_ft = math.radians(abs(turn_angle_deg)) * turn_radius_ft
    return GlideSegment(
        kind="turn",
        start_lat=start.latitude, start_lon=start.longitude,
        start_alt_agl_ft=start_alt, start_heading_deg=start_heading,
        end_lat=end_pos.latitude, end_lon=end_pos.longitude,
        end_alt_agl_ft=end_alt, end_heading_deg=end_heading,
        center_lat=center.latitude, center_lon=center.longitude,
        turn_radius_ft=turn_radius_ft,
        turn_angle_deg=sign * abs(turn_angle_deg),
        ground_distance_ft=arc_length_ft,
        label=label,
    )


def _final_leg_cost_with_slip(alt_at_F: float, final_leg_ft: float,
                                 glide_ratio: float) -> float:
    """Compute the altitude consumed on the final leg, allowing slip to
    absorb modest excess. Returns the cost in feet.

    If `alt_at_F <= final_leg_ft / GR`, the aircraft is at or below the
    normal glide path — no slip, cost = final_leg_ft / GR (aircraft will
    arrive short → impact handled by executor).

    If `alt_at_F > final_leg_ft / GR`, the aircraft has excess. Slip
    absorbs up to (final_leg_ft / (GR × SLIP_GR_MIN_FACTOR) − normal cost)
    of the excess. Beyond that the aircraft arrives high (returned cost
    is capped at the max-slip cost)."""
    gr = max(1.0, glide_ratio)
    cost_normal = final_leg_ft / gr
    cost_max_slip = final_leg_ft / max(1.0, gr * SLIP_GR_MIN_FACTOR)
    if alt_at_F <= cost_normal:
        return cost_normal
    return min(alt_at_F, cost_max_slip)


def _apply_initial_turn(start: GeoPoint, start_alt_ft: float,
                          start_heading_deg: float, target_heading_deg: float,
                          turn_radius_ft: float, glide_ratio: float,
                          label: str = "Initial turn"
                          ) -> tuple[Optional[GlideSegment], GeoPoint, float, float]:
    """Build the smoothing turn from `start_heading_deg` to
    `target_heading_deg`. Returns (segment_or_None, post_turn_pos,
    post_turn_alt, post_turn_heading). Returns None for the segment if the
    heading delta is < 2° (no meaningful turn)."""
    h_diff = _angle_diff_deg(target_heading_deg, start_heading_deg)
    if abs(h_diff) < 2.0:
        return None, start, start_alt_ft, start_heading_deg
    direction = "left" if h_diff < 0 else "right"
    turn_angle = abs(h_diff)
    arc_length_ft = math.radians(turn_angle) * turn_radius_ft
    alt_cost_ft = arc_length_ft / max(1.0, glide_ratio)
    end_alt = start_alt_ft - alt_cost_ft
    seg = _turn_segment_n(
        start=start, start_alt=start_alt_ft, start_heading=start_heading_deg,
        turn_angle_deg=turn_angle, turn_radius_ft=turn_radius_ft,
        direction=direction, end_alt=end_alt, label=label)
    end_pos = GeoPoint(seg.end_lat, seg.end_lon)
    return seg, end_pos, end_alt, seg.end_heading_deg


def _dubins_csc(p_start: GeoPoint, h_start_deg: float,
                  p_end: GeoPoint, h_end_deg: float,
                  R: float, direction: str
                  ) -> Optional[tuple[float, float, float, GeoPoint, GeoPoint]]:
    """Dubins CSC (Circle-Straight-Circle) path with same-direction turns.
    `direction` = "left" (LSL) or "right" (RSR).

    Returns (arc1_angle_deg, straight_dist_ft, arc2_angle_deg, t1, t2) where
    t1 and t2 are the tangent points on the two turn circles. The aircraft
    flies a circular arc of `arc1` from p_start to t1, then a straight from
    t1 to t2, then a circular arc of `arc2` from t2 to p_end. End heading is
    `h_end_deg` exactly (by construction).

    Returns None if circles coincide (degenerate)."""
    sign = -1.0 if direction == "left" else +1.0
    # Turn centers — perpendicular to heading on the turn-side.
    c1_bearing = _wrap_360(h_start_deg + sign * 90.0)
    c2_bearing = _wrap_360(h_end_deg + sign * 90.0)
    c1 = _point_at_bearing(p_start, c1_bearing, R)
    c2 = _point_at_bearing(p_end, c2_bearing, R)
    d_centers = _ft(c1, c2)
    if d_centers < 1e-3:
        return None
    # External tangent: parallel to the line c1→c2, offset R perpendicular on
    # the outside of both circles.
    c1c2_bearing = _bearing(c1, c2)
    outside_perp = _wrap_360(c1c2_bearing - sign * 90.0)
    t1 = _point_at_bearing(c1, outside_perp, R)
    t2 = _point_at_bearing(c2, outside_perp, R)
    # The straight-segment heading is the c1→c2 direction.
    tangent_heading = c1c2_bearing
    # Arc angles. CCW turn (LSL) → bearing decreases; CW turn (RSR) → bearing
    # increases. Encode that with `sign`.
    arc1 = (sign * (tangent_heading - h_start_deg)) % 360.0
    arc2 = (sign * (h_end_deg - tangent_heading)) % 360.0
    # If an arc comes out >270°, it's almost certainly a 1-2° wrap
    # artifact (the target heading was numerically just on the wrong
    # side of the forced direction). Treat it as zero — the aircraft
    # accepts a sub-degree heading mismatch rather than flying a near-
    # full loop to "correct" it.
    if arc1 > 270.0:
        arc1 = 0.0
    if arc2 > 270.0:
        arc2 = 0.0
    return arc1, _ft(t1, t2), arc2, t1, t2


def _spiral_segment(center: GeoPoint, start_alt: float, end_alt: float,
                     turn_radius_ft: float, n_turns: float,
                     bank_deg: float, direction: str,
                     start_heading: float, label: str = "") -> GlideSegment:
    """Spiral N turns at constant bank around `center`. The aircraft
    enters at `center + (radius, perp-to-start_heading)` and exits at a
    position offset by N full turns + the fractional remainder."""
    sign = -1.0 if direction == "left" else 1.0
    # Aircraft is on the orbit ring perpendicular to its heading
    radial_bearing_at_start = _wrap_360(start_heading - sign * 90.0)
    start_pos = _point_at_bearing(center, radial_bearing_at_start, turn_radius_ft)
    arc_length_ft = 2.0 * math.pi * turn_radius_ft * n_turns
    angle_traveled_deg = sign * n_turns * 360.0
    end_heading = _wrap_360(start_heading + angle_traveled_deg)
    radial_bearing_at_end = _wrap_360(end_heading - sign * 90.0)
    end_pos = _point_at_bearing(center, radial_bearing_at_end, turn_radius_ft)
    return GlideSegment(
        kind="spiral",
        start_lat=start_pos.latitude, start_lon=start_pos.longitude,
        start_alt_agl_ft=start_alt, start_heading_deg=start_heading,
        end_lat=end_pos.latitude, end_lon=end_pos.longitude,
        end_alt_agl_ft=end_alt, end_heading_deg=end_heading,
        center_lat=center.latitude, center_lon=center.longitude,
        turn_radius_ft=turn_radius_ft,
        spiral_turns=n_turns,
        spiral_bank_deg=bank_deg,
        spiral_direction=direction,
        ground_distance_ft=arc_length_ft,
        label=label,
    )


# =============================================================================
# Main planner
# =============================================================================

def plan_glide(*,
                 start_lat: float,
                 start_lon: float,
                 start_alt_agl_ft: float,
                 start_heading_deg: float,
                 touchdown_lat: float,
                 touchdown_lon: float,
                 touchdown_elev_ft: float,
                 runway_heading_deg: float,
                 best_glide_tas_kt: float,
                 glide_ratio: float,
                 max_bank_deg: float = MAX_BANK_DEG,
                 planning_bank_deg: float = PLANNING_BANK_DEG,
                 wind_dir_deg: float = 0.0,
                 wind_speed_kt: float = 0.0,
                 ) -> GlidePlan:
    """Compute a traffic-pattern engine-out glide trajectory.

    Pattern shape (always lateral; no overhead spiral — that's invisible at
    typical map zoom):

        start
          │ entry vector (descending)
          ▼
        D_entry  ── downwind (extended for excess alt) ──>  base_turn_start
                                                                │ base turn 90°
                                                                ▼
                                                            base_turn_end
                                                                │ base leg
                                                                ▼
                                                          final_turn_start
                                                                │ final turn 90°
                                                                ▼
        touchdown <── final ──  F  <───────────────────────────┘
    """

    start = GeoPoint(start_lat, start_lon)
    touchdown = GeoPoint(touchdown_lat, touchdown_lon)

    planning_bank_deg = min(planning_bank_deg, max_bank_deg)
    R = _turn_radius_ft(best_glide_tas_kt, planning_bank_deg)
    # Pattern offset is FIXED (visible scale); the PO180 turn uses a larger
    # radius (R_po180 = PATTERN_OFFSET/2) so the 180° closes geometrically.
    # That implies a shallower bank for the PO180, which is fine because
    # engine-out 180° is a conservative descending turn — pilots commonly
    # fly it at 15–25° bank to manage AOA, not max-bank.
    PATTERN_OFFSET_FT_local = PATTERN_OFFSET_FT
    R_po180 = PATTERN_OFFSET_FT_local / 2.0
    po180_bank_deg = math.degrees(math.atan(
        (best_glide_tas_kt * 1.68781) ** 2 / (G_FPS2 * R_po180)))

    # --- Position relative to runway -----------------------------------------
    cross_ft, along_ft = _cross_track_along_track_ft(
        touchdown, start, runway_heading_deg)
    on_final_side = along_ft < 0
    heading_diff = _angle_diff_deg(start_heading_deg, runway_heading_deg)

    reverse_runway = _wrap_360(runway_heading_deg + 180.0)

    final_wind_component_kt = wind_speed_kt * math.cos(
        math.radians(_angle_diff_deg(wind_dir_deg, runway_heading_deg)))

    # --- Smart pattern side: evaluate both sides and pick the one that
    # requires less ground distance from start to D_abeam (= less alt cost).
    # That naturally picks "same side as start" when start is lateral, but
    # picks the OPPOSITE side when start is e.g. on the upwind end of the
    # runway and crossing over is the natural play.
    def _side_geometry(side: str):
        sign = -1 if side == "left" else +1
        perp = _wrap_360(runway_heading_deg + sign * 90.0)
        Fp = _point_at_bearing(touchdown, reverse_runway, FINAL_LEG_FT)
        D_abeam_p = _point_at_bearing(touchdown, perp, PATTERN_OFFSET_FT_local)
        base_turn_start_p = _point_at_bearing(Fp, perp, PATTERN_OFFSET_FT_local)
        return sign, perp, Fp, D_abeam_p, base_turn_start_p

    # Quick comparison: pick side that minimizes dist(start, D_abeam).
    sign_L, perp_L, F_L, D_abeam_L, btss_L = _side_geometry("left")
    sign_R, perp_R, F_R, D_abeam_R, btss_R = _side_geometry("right")
    dist_L = _ft(start, D_abeam_L)
    dist_R = _ft(start, D_abeam_R)
    pattern_side = "left" if dist_L <= dist_R else "right"
    side_sign = sign_L if pattern_side == "left" else sign_R
    perp_to_pattern = perp_L if pattern_side == "left" else perp_R
    perp_from_pattern = _wrap_360(runway_heading_deg - side_sign * 90.0)
    F = F_L if pattern_side == "left" else F_R
    D_abeam = D_abeam_L if pattern_side == "left" else D_abeam_R
    base_turn_start = btss_L if pattern_side == "left" else btss_R

    # --- Energy budget -------------------------------------------------------
    direct_dist_ft = _ft(start, touchdown)
    direct_dist_nm = direct_dist_ft / FT_PER_NM
    track_to_touchdown = (_bearing(start, touchdown)
                            if direct_dist_ft > 1e-3 else runway_heading_deg)
    direct_glide_alt_ft = _wind_corrected_alt_cost_ft(
        direct_dist_ft, track_to_touchdown, best_glide_tas_kt,
        glide_ratio, wind_dir_deg, wind_speed_kt)
    arrival_alt_agl = start_alt_agl_ft - direct_glide_alt_ft

    excess_at_high_key = arrival_alt_agl - HIGH_KEY_AGL_FT
    excess_at_low_key = arrival_alt_agl - LOW_KEY_AGL_FT

    # Glide cost from start to D_abeam (the standard pattern entry).
    entry_dist_ft = _ft(start, D_abeam)
    track_to_abeam = (_bearing(start, D_abeam)
                        if entry_dist_ft > 1e-3 else runway_heading_deg)
    entry_alt_cost_ft = _wind_corrected_alt_cost_ft(
        entry_dist_ft, track_to_abeam, best_glide_tas_kt,
        glide_ratio, wind_dir_deg, wind_speed_kt)
    alt_at_D_abeam = start_alt_agl_ft - entry_alt_cost_ft

    # Pattern altitude budget (no extension): downwind (FINAL_LEG) →
    # continuous 180° PO180 (πR_po180) → final (FINAL_LEG). No separate base
    # leg — that's the squared-off shape we don't want.
    pattern_min_ground_ft = 2.0 * FINAL_LEG_FT + math.pi * R_po180
    pattern_min_alt_ft = pattern_min_ground_ft / max(1.0, glide_ratio)

    # --- Strategy selection -------------------------------------------------
    key_positions: list[KeyPosition] = []
    key_positions.append(KeyPosition(
        "touchdown", touchdown.latitude, touchdown.longitude,
        0.0, runway_heading_deg))
    key_positions.append(KeyPosition(
        "F", F.latitude, F.longitude,
        SHORT_FINAL_AGL_FT, runway_heading_deg))

    def _diag(**extra) -> GlideDiagnostics:
        d = dict(
            start_alt_msl_ft=start_alt_agl_ft + touchdown_elev_ft,
            start_alt_agl_ft=start_alt_agl_ft,
            direct_dist_nm=direct_dist_nm,
            direct_glide_alt_ft=direct_glide_alt_ft,
            arrival_alt_agl_ft=arrival_alt_agl,
            excess_at_high_key_ft=excess_at_high_key,
            excess_at_low_key_ft=excess_at_low_key,
            pattern_side=pattern_side,
            on_final_side=on_final_side,
            best_glide_tas_kt=best_glide_tas_kt,
            glide_ratio=glide_ratio,
            planning_bank_deg=planning_bank_deg,
            max_bank_deg=max_bank_deg,
            turn_radius_ft=R,
            spiral_turns=0.0,
            spiral_bank_deg=0.0,
            wind_dir_deg=wind_dir_deg,
            wind_speed_kt=wind_speed_kt,
            final_wind_component_kt=final_wind_component_kt,
        )
        d.update(extra)
        return _diagnostics(**d)

    # Reach check: can we even glide direct to touchdown?
    if arrival_alt_agl < -100.0:
        return GlidePlan(
            segments=[_straight_segment(
                start, start_alt_agl_ft, touchdown, max(0.0, arrival_alt_agl),
                label="Best-effort glide (won't reach field)")],
            key_positions=key_positions,
            diagnostics=_diag(
                approach_strategy="off_field", feasible=False,
                failure_reason=(
                    f"{(direct_glide_alt_ft - start_alt_agl_ft):.0f} ft short. "
                    f"Need {direct_glide_alt_ft:.0f} ft AGL minimum; "
                    f"have {start_alt_agl_ft:.0f}."
                )))

    # Straight-in eligibility — POSITION-only check (drop the heading gate).
    # If the aircraft is behind the threshold and close to the extended
    # centerline, fly straight in regardless of current heading — the
    # initial Dubins turn handles whatever heading change is needed.
    straight_in_possible = False
    if on_final_side and abs(cross_ft) <= STRAIGHT_IN_MAX_XTRACK_FT:
        # Direct glide from start to F (the final fix).
        d_start_to_F = _ft(start, F)
        trk_to_F = (_bearing(start, F)
                      if d_start_to_F > 1e-3 else runway_heading_deg)
        cost_to_F = _wind_corrected_alt_cost_ft(
            d_start_to_F, trk_to_F, best_glide_tas_kt,
            glide_ratio, wind_dir_deg, wind_speed_kt)
        cost_F_to_td = _wind_corrected_alt_cost_ft(
            FINAL_LEG_FT, runway_heading_deg, best_glide_tas_kt,
            glide_ratio, wind_dir_deg, wind_speed_kt)
        arrival_alt_straight_in = (start_alt_agl_ft - cost_to_F
                                      - cost_F_to_td)
        # Straight-in is acceptable if we'd arrive within +1500/−100 ft of
        # the touchdown surface. The high end is wide because a real pilot
        # can slip / S-turn on final to bleed up to ~1000+ ft of excess.
        # Above that, the user's guidance is "spiral overhead first" — so
        # we fall through to the orbit-then-pattern branch.
        if -100.0 <= arrival_alt_straight_in <= 1500.0:
            straight_in_possible = True

    if straight_in_possible:
        # Dubins CSC from (start, start_heading) to (F, runway_heading) so
        # the trajectory smoothly turns to align with the runway, glides
        # straight to F, and exits tangent to the centerline.
        pos = start; alt = start_alt_agl_ft; hdg = start_heading_deg
        si_segments: list[GlideSegment] = []
        d_lsl = _dubins_csc(pos, hdg, F, runway_heading_deg, R, "left")
        d_rsr = _dubins_csc(pos, hdg, F, runway_heading_deg, R, "right")
        chosen = None
        if d_lsl is not None and d_rsr is not None:
            len_l = (math.radians(d_lsl[0]) * R + d_lsl[1]
                       + math.radians(d_lsl[2]) * R)
            len_r = (math.radians(d_rsr[0]) * R + d_rsr[1]
                       + math.radians(d_rsr[2]) * R)
            chosen, dub_dir = ((d_lsl, "left") if len_l <= len_r
                                  else (d_rsr, "right"))
        elif d_lsl is not None:
            chosen, dub_dir = d_lsl, "left"
        elif d_rsr is not None:
            chosen, dub_dir = d_rsr, "right"
        if chosen is not None:
            a1, s_d, a2, t1p, t2p = chosen
            if a1 > 1.0:
                arc_len = math.radians(a1) * R
                cost = arc_len / max(1.0, glide_ratio)
                seg = _turn_segment_n(
                    start=pos, start_alt=alt, start_heading=hdg,
                    turn_angle_deg=a1, turn_radius_ft=R,
                    direction=dub_dir, end_alt=alt - cost,
                    label="Straight-in turn 1")
                si_segments.append(seg); pos = GeoPoint(seg.end_lat, seg.end_lon)
                alt -= cost; hdg = seg.end_heading_deg
            if s_d > 50.0:
                trk = _bearing(pos, t2p)
                cost = _wind_corrected_alt_cost_ft(
                    s_d, trk, best_glide_tas_kt, glide_ratio,
                    wind_dir_deg, wind_speed_kt)
                si_segments.append(_straight_segment(
                    pos, alt, t2p, alt - cost,
                    label="Straight-in tangent"))
                pos = t2p; alt -= cost; hdg = trk
            if a2 > 1.0:
                arc_len = math.radians(a2) * R
                cost = arc_len / max(1.0, glide_ratio)
                seg = _turn_segment_n(
                    start=pos, start_alt=alt, start_heading=hdg,
                    turn_angle_deg=a2, turn_radius_ft=R,
                    direction=dub_dir, end_alt=alt - cost,
                    label="Straight-in turn 2 (align)")
                si_segments.append(seg); pos = GeoPoint(seg.end_lat, seg.end_lon)
                alt -= cost; hdg = seg.end_heading_deg
        # Glide from current position to F if not already there.
        d_remain = _ft(pos, F)
        if d_remain > 50.0:
            cost = _wind_corrected_alt_cost_ft(
                d_remain, runway_heading_deg, best_glide_tas_kt,
                glide_ratio, wind_dir_deg, wind_speed_kt)
            si_segments.append(_straight_segment(
                pos, alt, F, alt - cost,
                label="Straight-in glide to final fix"))
            alt = alt - cost
        # Short final to touchdown — slip absorbs modest excess; otherwise
        # alt may go below zero (executor truncates at impact).
        cost_normal_wind = _wind_corrected_alt_cost_ft(
            FINAL_LEG_FT, runway_heading_deg, best_glide_tas_kt,
            glide_ratio, wind_dir_deg, wind_speed_kt)
        gr_effective_final = FINAL_LEG_FT / max(1e-3, cost_normal_wind)
        cost_final = _final_leg_cost_with_slip(
            alt, FINAL_LEG_FT, gr_effective_final)
        alt_at_td = alt - cost_final
        si_segments.append(_straight_segment(
            F, alt, touchdown, alt_at_td, label="Final → touchdown"))
        return GlidePlan(
            segments=si_segments, key_positions=key_positions,
            diagnostics=_diag(approach_strategy="straight_in",
                                feasible=(alt_at_td <= 100.0),
                                failure_reason=None))

    # Standard lateral pattern. Solve for the downwind extension that closes
    # the energy budget:
    #   start_alt = entry_cost(start→D_entry) + extension/GR + pattern_min_alt
    # `extension` and `entry_cost` are coupled (D_entry moves with extension),
    # so we bisect on the residual:
    #   f(ext) = (start_alt − entry_cost(ext)) − ext/GR − pattern_min_alt
    # f is monotonically decreasing in ext for any start at/behind the field.
    def _f_residual(ext: float) -> float:
        D_try = _point_at_bearing(D_abeam, runway_heading_deg, ext)
        d_try = _ft(start, D_try)
        trk_try = (_bearing(start, D_try)
                     if d_try > 1e-3 else runway_heading_deg)
        cost = _wind_corrected_alt_cost_ft(
            d_try, trk_try, best_glide_tas_kt,
            glide_ratio, wind_dir_deg, wind_speed_kt)
        return (start_alt_agl_ft - cost) - ext / max(1.0, glide_ratio) \
               - pattern_min_alt_ft

    needs_orbit = False
    ext_lo, ext_hi = 0.0, MAX_EXTENSION_FT
    if _f_residual(ext_lo) <= 0.0:
        extension_ft = 0.0
    elif _f_residual(ext_hi) >= 0.0:
        # Even max-extension downwind can't absorb the excess — must orbit
        # overhead the field first to bleed altitude per FAA technique
        # (stay near/over the field; don't fly away from it).
        extension_ft = MAX_EXTENSION_FT
        needs_orbit = True
    else:
        for _ in range(30):
            mid = 0.5 * (ext_lo + ext_hi)
            f_mid = _f_residual(mid)
            if abs(f_mid) < 10.0:
                ext_lo = ext_hi = mid
                break
            if f_mid > 0.0:
                ext_lo = mid
            else:
                ext_hi = mid
        extension_ft = 0.5 * (ext_lo + ext_hi)

    # If energy is BELOW pattern_min_alt by more than ~200 ft, pattern is
    # too long. Tighten by skipping the base leg (continuous 180° base→final).
    energy_short_ft = pattern_min_alt_ft - alt_at_D_abeam
    if energy_short_ft > 200.0:
        # Tight pattern: continuous 180° from D_abeam to F (PO180-style).
        # Use a tighter radius (matching the 2R = PATTERN_OFFSET constraint).
        po180_radius = R
        po180_arc = _turn_segment_180(
            start=D_abeam, start_alt=alt_at_D_abeam,
            start_heading=reverse_runway,
            end=F, end_alt=SHORT_FINAL_AGL_FT,
            end_heading=runway_heading_deg,
            turn_radius_ft=po180_radius,
            direction=pattern_side,
            label="Tight base→final 180°")
        segments = [
            _straight_segment(start, start_alt_agl_ft, D_abeam,
                                 alt_at_D_abeam,
                                 label="Direct to abeam touchdown"),
            po180_arc,
            _straight_segment(F, SHORT_FINAL_AGL_FT, touchdown, 0.0,
                                 label="Final → touchdown"),
        ]
        key_positions.append(KeyPosition(
            "D_abeam", D_abeam.latitude, D_abeam.longitude,
            alt_at_D_abeam, reverse_runway))
        return GlidePlan(segments=segments,
                          key_positions=key_positions,
                          diagnostics=_diag(
                              approach_strategy="tight_pattern",
                              feasible=(alt_at_D_abeam >= SHORT_FINAL_AGL_FT),
                              failure_reason=(
                                  None if alt_at_D_abeam >= SHORT_FINAL_AGL_FT
                                  else
                                  f"Energy short by {energy_short_ft:.0f} ft "
                                  f"at pattern entry. Need a steeper or "
                                  f"shorter approach.")))

    # Standard lateral pattern with downwind extension.
    # D_entry = abeam touchdown shifted toward the UPWIND end so the downwind
    # leg passes back over abeam touchdown and continues to base_turn_start.
    D_entry = _point_at_bearing(D_abeam, runway_heading_deg, extension_ft)

    # Forward integration of altitude through each leg.
    segments: list[GlideSegment] = []
    pos = start
    alt = start_alt_agl_ft
    hdg = start_heading_deg

    # 0. Overhead orbit (if extension cap hit). Orbit at ORBIT_RADIUS_FT
    # centered on the touchdown, spiraling until alt arrives at the level
    # where the downwind extension can absorb the rest. The orbit direction
    # matches the pattern side so the exit naturally feeds the downwind.
    if needs_orbit:
        # Initial turn toward the field (touchdown) so the spiral entry
        # tangent matches the inbound heading.
        target_hdg_to_td = (_bearing(pos, touchdown)
                              if _ft(pos, touchdown) > 1e-3 else hdg)
        turn_seg, pos, alt, hdg = _apply_initial_turn(
            pos, alt, hdg, target_hdg_to_td, R, glide_ratio,
            label="Initial turn toward field")
        if turn_seg is not None:
            segments.append(turn_seg)
        # Glide from post-turn position to the orbit perimeter (on the line
        # from touchdown to pos, at ORBIT_RADIUS_FT).
        dist_to_td = _ft(pos, touchdown)
        if dist_to_td > ORBIT_RADIUS_FT:
            bearing_td_to_pos = _bearing(touchdown, pos)
            orbit_entry = _point_at_bearing(
                touchdown, bearing_td_to_pos, ORBIT_RADIUS_FT)
            d_to_orbit = _ft(pos, orbit_entry)
            trk = (_bearing(pos, orbit_entry)
                     if d_to_orbit > 1e-3 else hdg)
            cost = _wind_corrected_alt_cost_ft(
                d_to_orbit, trk, best_glide_tas_kt,
                glide_ratio, wind_dir_deg, wind_speed_kt)
            alt_at_orbit = alt - cost
            segments.append(_straight_segment(
                pos, alt, orbit_entry, alt_at_orbit,
                label="Glide to overhead orbit"))
            pos = orbit_entry
            alt = alt_at_orbit
            hdg = trk
        # Compute orbit count by iterating: each candidate `n` gives an
        # actual exit position, an actual transition cost, and a touchdown
        # arrival altitude. We bisect on `n` to drive the arrival to ~0.
        orbit_bank_deg = math.degrees(math.atan(
            (best_glide_tas_kt * 1.68781) ** 2
            / (G_FPS2 * ORBIT_RADIUS_FT)))
        spiral_alt_per_turn = (2.0 * math.pi * ORBIT_RADIUS_FT
                                 / max(1.0, glide_ratio))
        sign_dir = -1.0 if pattern_side == "left" else +1.0

        def _orbit_arrival_residual(n: float) -> tuple[float, GeoPoint, float]:
            """Returns (touchdown_arrival_alt − 0, exit_pos, exit_alt)."""
            spiral_burn = n * spiral_alt_per_turn
            exit_alt = alt - spiral_burn
            # Spiral exit position: aircraft heads end_heading after n turns,
            # so the radial bearing at exit = end_heading − sign × 90°.
            end_heading = _wrap_360(hdg + sign_dir * n * 360.0)
            radial_at_end = _wrap_360(end_heading - sign_dir * 90.0)
            exit_pos = _point_at_bearing(
                touchdown, radial_at_end, ORBIT_RADIUS_FT)
            transition_dist = _ft(exit_pos, D_abeam)
            transition_cost = transition_dist / max(1.0, glide_ratio)
            arrival_at_td = (exit_alt - transition_cost
                               - pattern_min_alt_ft)
            return arrival_at_td, exit_pos, exit_alt

        # Bisect on n_turns in [ORBIT_MIN_TURNS, ORBIT_MAX_TURNS].
        n_lo, n_hi = ORBIT_MIN_TURNS, ORBIT_MAX_TURNS
        r_lo = _orbit_arrival_residual(n_lo)[0]
        r_hi = _orbit_arrival_residual(n_hi)[0]
        if r_lo <= 0.0:
            n_turns = n_lo
        elif r_hi >= 0.0:
            n_turns = n_hi
        else:
            for _ in range(20):
                n_mid = 0.5 * (n_lo + n_hi)
                r_mid, _ep, _ea = _orbit_arrival_residual(n_mid)
                if abs(r_mid) < 25.0:
                    n_lo = n_hi = n_mid
                    break
                if r_mid > 0.0:
                    n_lo = n_mid
                else:
                    n_hi = n_mid
            n_turns = 0.5 * (n_lo + n_hi)
        alt_after_spiral = alt - n_turns * spiral_alt_per_turn
        spiral_seg = _spiral_segment(
            center=touchdown, start_alt=alt, end_alt=alt_after_spiral,
            turn_radius_ft=ORBIT_RADIUS_FT, n_turns=n_turns,
            bank_deg=orbit_bank_deg, direction=pattern_side,
            start_heading=hdg,
            label=f"Overhead orbit ({n_turns:.2f} turns)")
        segments.append(spiral_seg)
        pos = GeoPoint(spiral_seg.end_lat, spiral_seg.end_lon)
        alt = alt_after_spiral
        hdg = spiral_seg.end_heading_deg
        key_positions.append(KeyPosition(
            "orbit_center", touchdown.latitude, touchdown.longitude,
            (alt + start_alt_agl_ft) / 2.0, runway_heading_deg))
        # After orbit, head to D_abeam directly (no extension needed; we
        # bled the excess overhead).
        D_entry = D_abeam
        extension_ft = 0.0

    # 1. Dubins CSC entry to D_entry tangent to downwind heading. This gives
    # a smooth turn → straight → turn that ends EXACTLY at D_entry heading
    # reverse_runway — no spot turn, no kink between entry and downwind.
    # Try both LSL and RSR, pick the one with shorter total ground length.
    dubins_lsl = _dubins_csc(pos, hdg, D_entry, reverse_runway, R, "left")
    dubins_rsr = _dubins_csc(pos, hdg, D_entry, reverse_runway, R, "right")
    chosen = None
    if dubins_lsl is not None and dubins_rsr is not None:
        len_lsl = (math.radians(dubins_lsl[0]) * R
                     + dubins_lsl[1]
                     + math.radians(dubins_lsl[2]) * R)
        len_rsr = (math.radians(dubins_rsr[0]) * R
                     + dubins_rsr[1]
                     + math.radians(dubins_rsr[2]) * R)
        if len_lsl <= len_rsr:
            chosen, dub_dir = dubins_lsl, "left"
        else:
            chosen, dub_dir = dubins_rsr, "right"
    elif dubins_lsl is not None:
        chosen, dub_dir = dubins_lsl, "left"
    elif dubins_rsr is not None:
        chosen, dub_dir = dubins_rsr, "right"

    if chosen is not None:
        arc1_ang, straight_dist, arc2_ang, t1_pos, t2_pos = chosen
        # Arc 1 — initial turn from start
        if arc1_ang > 1.0:
            arc1_len = math.radians(arc1_ang) * R
            cost1 = arc1_len / max(1.0, glide_ratio)
            alt_after_arc1 = alt - cost1
            seg1 = _turn_segment_n(
                start=pos, start_alt=alt, start_heading=hdg,
                turn_angle_deg=arc1_ang, turn_radius_ft=R,
                direction=dub_dir, end_alt=alt_after_arc1,
                label="Entry turn 1")
            segments.append(seg1)
            pos = GeoPoint(seg1.end_lat, seg1.end_lon)
            alt = alt_after_arc1
            hdg = seg1.end_heading_deg
        # Tangent straight
        if straight_dist > 50.0:
            trk = _bearing(pos, t2_pos) if straight_dist > 1e-3 else hdg
            cost_s = _wind_corrected_alt_cost_ft(
                straight_dist, trk, best_glide_tas_kt,
                glide_ratio, wind_dir_deg, wind_speed_kt)
            alt_after_straight = alt - cost_s
            segments.append(_straight_segment(
                pos, alt, t2_pos, alt_after_straight,
                label="Entry tangent to downwind"))
            pos = t2_pos
            alt = alt_after_straight
            hdg = trk
        # Arc 2 — final smoothing onto downwind
        if arc2_ang > 1.0:
            arc2_len = math.radians(arc2_ang) * R
            cost2 = arc2_len / max(1.0, glide_ratio)
            alt_after_arc2 = alt - cost2
            seg2 = _turn_segment_n(
                start=pos, start_alt=alt, start_heading=hdg,
                turn_angle_deg=arc2_ang, turn_radius_ft=R,
                direction=dub_dir, end_alt=alt_after_arc2,
                label="Entry turn 2 (join downwind)")
            segments.append(seg2)
            pos = GeoPoint(seg2.end_lat, seg2.end_lon)
            alt = alt_after_arc2
            hdg = seg2.end_heading_deg
        alt_at_D_entry = alt
    else:
        # Fallback: straight glide to D_entry
        d_to_entry = _ft(pos, D_entry)
        trk_to_entry = (_bearing(pos, D_entry)
                          if d_to_entry > 1e-3 else runway_heading_deg)
        cost_entry = _wind_corrected_alt_cost_ft(
            d_to_entry, trk_to_entry, best_glide_tas_kt,
            glide_ratio, wind_dir_deg, wind_speed_kt)
        alt_at_D_entry = alt - cost_entry
        segments.append(_straight_segment(
            pos, alt, D_entry, alt_at_D_entry,
            label="Entry to downwind"))
        pos = D_entry
        alt = alt_at_D_entry
        hdg = reverse_runway

    # 2. Downwind: current position (= post-join-turn, may be slightly off
    # D_entry) → base_turn_start.
    dw_dist = _ft(pos, base_turn_start)
    dw_alt_cost = _wind_corrected_alt_cost_ft(
        dw_dist, reverse_runway, best_glide_tas_kt,
        glide_ratio, wind_dir_deg, wind_speed_kt)
    alt_at_base_turn_start = alt - dw_alt_cost
    segments.append(_straight_segment(
        pos, alt, base_turn_start, alt_at_base_turn_start,
        label="Downwind"))
    alt = alt_at_base_turn_start

    # 3. Continuous 180° PO180 from base_turn_start to F at radius R_po180.
    # One smooth arc — no separate base + final turns.
    po180_arc_ft = math.pi * R_po180
    po180_alt_cost = po180_arc_ft / max(1.0, glide_ratio)
    alt_at_F = alt - po180_alt_cost
    segments.append(_turn_segment_180(
        start=base_turn_start, start_alt=alt,
        start_heading=reverse_runway,
        end=F, end_alt=alt_at_F,
        end_heading=runway_heading_deg,
        turn_radius_ft=R_po180,
        direction=pattern_side,
        label="PO180 base→final"))
    alt = alt_at_F

    # 4. Final leg: F → touchdown
    final_alt_cost = _wind_corrected_alt_cost_ft(
        FINAL_LEG_FT, runway_heading_deg, best_glide_tas_kt,
        glide_ratio, wind_dir_deg, wind_speed_kt)
    alt_at_touchdown = max(0.0, alt - final_alt_cost)
    segments.append(_straight_segment(
        F, alt_at_F, touchdown, alt_at_touchdown,
        label="Final → touchdown"))

    key_positions.append(KeyPosition(
        "D_entry", D_entry.latitude, D_entry.longitude,
        alt_at_D_entry, reverse_runway))
    key_positions.append(KeyPosition(
        "D_abeam", D_abeam.latitude, D_abeam.longitude,
        alt_at_D_entry - (extension_ft / max(1.0, glide_ratio)),
        reverse_runway))
    key_positions.append(KeyPosition(
        "base_turn_start", base_turn_start.latitude, base_turn_start.longitude,
        alt_at_base_turn_start, reverse_runway))

    return GlidePlan(
        segments=segments,
        key_positions=key_positions,
        diagnostics=_diag(
            approach_strategy=("orbit_then_pattern" if needs_orbit
                                  else "lateral_pattern"),
            spiral_turns=(n_turns if needs_orbit else 0.0),
            spiral_bank_deg=(orbit_bank_deg if needs_orbit else 0.0),
            feasible=(alt_at_touchdown <= 50.0),
            failure_reason=(
                None if alt_at_touchdown <= 50.0
                else f"Arrives {alt_at_touchdown:.0f} ft high at threshold. "
                       f"Slip or S-turn on downwind to bleed more."),
        ),
    )


# =============================================================================
# Top-level entrypoint — drop-in replacement for simulate_engineout_glide
# =============================================================================

# =============================================================================
# Backbone planner — predefine the ideal engine-out backbone, find the latest
# reachable waypoint to join, build a smooth Dubins connection, then follow
# the backbone to touchdown. Inspired by the user's "baskets + perfect
# profiles" approach: explicit join points beats ad-hoc strategy branching.
# =============================================================================

@dataclass
class _Waypoint:
    name: str
    pos: GeoPoint
    ideal_alt_agl_ft: float
    heading_into_deg: float  # heading the aircraft should hold when joining


def _build_backbone(touchdown: GeoPoint, runway_heading_deg: float,
                     pattern_side: str, R_po180: float,
                     glide_ratio: float,
                     final_leg_ft: Optional[float] = None
                     ) -> list[_Waypoint]:
    """Build the backbone waypoints for the given pattern side. The IDEAL
    altitude at each waypoint is computed backward from touchdown — that's
    the altitude at which the aircraft naturally arrives at this WP if it
    flies the backbone forward to touchdown.

    `final_leg_ft` overrides the default FINAL_LEG_FT — shifts F further
    behind the threshold AND moves base back to match (base is abeam F),
    which extends BOTH the downwind and the final legs by the same amount.
    LK stays abeam touchdown.

    Order: 0=overhead → 1=low_key → 2=base → 3=F → 4=touchdown.
    """
    fl = FINAL_LEG_FT if final_leg_ft is None else final_leg_ft
    sign = -1 if pattern_side == "left" else +1
    reverse_runway = _wrap_360(runway_heading_deg + 180.0)
    perp_to_pattern = _wrap_360(runway_heading_deg + sign * 90.0)

    F_pos = _point_at_bearing(touchdown, reverse_runway, fl)
    base_pos = _point_at_bearing(F_pos, perp_to_pattern, PATTERN_OFFSET_FT)
    LK_pos = _point_at_bearing(touchdown, perp_to_pattern, PATTERN_OFFSET_FT)
    overhead_pos = touchdown

    GR = max(1.0, glide_ratio)
    alt_TD = 0.0
    alt_F = alt_TD + fl / GR
    alt_base = alt_F + (math.pi * R_po180) / GR
    # Downwind length = fl (since base is at along=-fl, LK at along=0).
    alt_LK = alt_base + fl / GR
    # Overhead alt = LK + transition cost (~ PATTERN_OFFSET / GR), with a
    # floor at the FAA-standard HIGH_KEY altitude (1500 AGL).
    alt_overhead = max(alt_LK + PATTERN_OFFSET_FT / GR, HIGH_KEY_AGL_FT)

    return [
        _Waypoint("overhead", overhead_pos, alt_overhead, runway_heading_deg),
        _Waypoint("low_key", LK_pos, alt_LK, reverse_runway),
        _Waypoint("base", base_pos, alt_base, reverse_runway),
        _Waypoint("F", F_pos, alt_F, runway_heading_deg),
        _Waypoint("touchdown", touchdown, alt_TD, runway_heading_deg),
    ]


MAX_DOWNWIND_EXTENSION_FT = 6000.0   # 1 NM cap on downwind extension
                                        # (beyond this we orbit overhead —
                                        # more compact than a long detour)
# When the planner is about to spiral, it first tries to absorb the excess
# by GROWING THE PATTERN: shifting F further behind threshold (which also
# lengthens the downwind, since base sits abeam F). Every 1 ft of extra
# final length adds (2/GR) ft of altitude absorption — twice as efficient
# per foot as a one-sided downwind extension. The result is a single
# larger PO180 sweep instead of a tight overhead spiral plus a small turn.
FINAL_LEG_MAX_EXTENSION_FT = 6000.0   # 1 NM cap on extra final beyond default


def _find_join_wp(start: GeoPoint, start_alt_agl_ft: float,
                    waypoints: list[_Waypoint], best_glide_tas_kt: float,
                    glide_ratio: float, wind_dir_deg: float,
                    wind_speed_kt: float,
                    aligned_straight_in: bool = False
                    ) -> tuple[int, float]:
    """Find the join waypoint that best fits the aircraft's energy.

    Priority (latest to earliest):
      WP_F:    tight fit (±400 ft) by default — modified straight-in.
               When `aligned_straight_in` is True (aircraft on final side
               and within xtrack tolerance), the F margin widens to
               +1500 ft because slip/S-turn on final can bleed up to
               ~1000+ ft of excess — better than detouring to LK.
      WP_base: tight fit (±400 ft) — direct base entry, skip downwind
      WP_LK:   WIDE — absorbs excess via downwind extension up to 1 NM
      WP_overhead: last-resort spiral when even max downwind extension
                   can't absorb the excess.

    Returns (wp_idx, arrival_alt_at_wp_with_direct_glide)."""
    MARGIN_LOW = -50.0
    MARGIN_HIGH_TIGHT = 400.0
    MARGIN_HIGH_F_ALIGNED = 1500.0   # slip handles modest excess on final
    # Downwind extension converts altitude excess into ground distance at GR.
    MARGIN_HIGH_LK = MAX_DOWNWIND_EXTENSION_FT / max(1.0, glide_ratio)

    arrivals = []
    for wp in waypoints[:-1]:
        d = _ft(start, wp.pos)
        trk = _bearing(start, wp.pos) if d > 1e-3 else 0.0
        cost = _wind_corrected_alt_cost_ft(
            d, trk, best_glide_tas_kt, glide_ratio,
            wind_dir_deg, wind_speed_kt)
        arrivals.append(start_alt_agl_ft - cost)

    # WP_F (idx 3): tight unless aligned-on-final (then we accept more
    # excess and let slip/S-turn handle the bleed).
    F_wp = waypoints[3]; F_arr = arrivals[3]
    f_high = (MARGIN_HIGH_F_ALIGNED if aligned_straight_in
                else MARGIN_HIGH_TIGHT)
    if (F_wp.ideal_alt_agl_ft + MARGIN_LOW <= F_arr
            <= F_wp.ideal_alt_agl_ft + f_high):
        return 3, F_arr

    # WP_base (idx 2): tight
    base_wp = waypoints[2]; base_arr = arrivals[2]
    if (base_wp.ideal_alt_agl_ft + MARGIN_LOW <= base_arr
            <= base_wp.ideal_alt_agl_ft + MARGIN_HIGH_TIGHT):
        return 2, base_arr

    # WP_LK (idx 1): wide — extension absorbs excess
    LK_wp = waypoints[1]; LK_arr = arrivals[1]
    if (LK_wp.ideal_alt_agl_ft + MARGIN_LOW <= LK_arr
            <= LK_wp.ideal_alt_agl_ft + MARGIN_HIGH_LK):
        return 1, LK_arr

    # WP_overhead — orbit absorbs excess beyond the extension budget
    if arrivals[0] >= waypoints[0].ideal_alt_agl_ft - MARGIN_LOW:
        return 0, arrivals[0]

    # Too low everywhere — best-effort straight-in to F
    return 3, F_arr


def _connect_via_dubins(start: GeoPoint, start_alt: float,
                          start_heading: float, target_pos: GeoPoint,
                          target_heading: float, R: float,
                          best_glide_tas_kt: float, glide_ratio: float,
                          wind_dir_deg: float, wind_speed_kt: float,
                          label_prefix: str = "Entry",
                          force_direction: Optional[str] = None
                          ) -> tuple[list[GlideSegment], GeoPoint, float, float]:
    """Smooth Dubins CSC connection from (start, start_heading) to
    (target_pos, target_heading).

    If `force_direction` is "left" or "right", only that Dubins family
    (LSL or RSR) is used — this is the pilot-natural rule: all turns in a
    pattern should be the SAME direction (no flip-flop between left/right
    mid-trajectory). When force_direction is None, the shorter of LSL/RSR
    is chosen.

    Returns (segments, end_pos, end_alt, end_heading)."""
    segments: list[GlideSegment] = []
    pos = start; alt = start_alt; hdg = start_heading

    # Compute both LSL and RSR. "Soft" direction forcing: if a preferred
    # direction is given AND its total arc is reasonable (<240°), use it;
    # otherwise fall back to the shorter option. This prevents the spiral-
    # at-start case where forcing matching direction would require a
    # 300°+ initial turn.
    d_lsl = _dubins_csc(pos, hdg, target_pos, target_heading, R, "left")
    d_rsr = _dubins_csc(pos, hdg, target_pos, target_heading, R, "right")
    chosen = None; dub_dir = None
    MAX_FORCED_ARC = 240.0

    if force_direction == "left" and d_lsl is not None:
        if d_lsl[0] + d_lsl[2] <= MAX_FORCED_ARC:
            chosen, dub_dir = d_lsl, "left"
    elif force_direction == "right" and d_rsr is not None:
        if d_rsr[0] + d_rsr[2] <= MAX_FORCED_ARC:
            chosen, dub_dir = d_rsr, "right"

    if chosen is None:
        # Pick whichever is shorter.
        if d_lsl is not None and d_rsr is not None:
            len_l = (math.radians(d_lsl[0]) * R + d_lsl[1]
                       + math.radians(d_lsl[2]) * R)
            len_r = (math.radians(d_rsr[0]) * R + d_rsr[1]
                       + math.radians(d_rsr[2]) * R)
            chosen, dub_dir = ((d_lsl, "left") if len_l <= len_r
                                  else (d_rsr, "right"))
        elif d_lsl is not None:
            chosen, dub_dir = d_lsl, "left"
        elif d_rsr is not None:
            chosen, dub_dir = d_rsr, "right"

    if chosen is None:
        d = _ft(pos, target_pos)
        if d > 1e-3:
            trk = _bearing(pos, target_pos)
            cost = _wind_corrected_alt_cost_ft(
                d, trk, best_glide_tas_kt, glide_ratio,
                wind_dir_deg, wind_speed_kt)
            segments.append(_straight_segment(
                pos, alt, target_pos, alt - cost,
                label=f"{label_prefix} direct"))
            pos = target_pos; alt -= cost; hdg = trk
        return segments, pos, alt, hdg

    arc1, straight_d, arc2, _t1, t2 = chosen
    if arc1 > 1.0:
        cost = math.radians(arc1) * R / max(1.0, glide_ratio)
        seg = _turn_segment_n(
            start=pos, start_alt=alt, start_heading=hdg,
            turn_angle_deg=arc1, turn_radius_ft=R,
            direction=dub_dir, end_alt=alt - cost,
            label=f"{label_prefix} turn 1")
        segments.append(seg)
        pos = GeoPoint(seg.end_lat, seg.end_lon)
        alt -= cost; hdg = seg.end_heading_deg
    if straight_d > 30.0:
        trk = _bearing(pos, t2) if straight_d > 1e-3 else hdg
        cost = _wind_corrected_alt_cost_ft(
            straight_d, trk, best_glide_tas_kt, glide_ratio,
            wind_dir_deg, wind_speed_kt)
        segments.append(_straight_segment(
            pos, alt, t2, alt - cost,
            label=f"{label_prefix} tangent"))
        pos = t2; alt -= cost; hdg = trk
    if arc2 > 1.0:
        cost = math.radians(arc2) * R / max(1.0, glide_ratio)
        seg = _turn_segment_n(
            start=pos, start_alt=alt, start_heading=hdg,
            turn_angle_deg=arc2, turn_radius_ft=R,
            direction=dub_dir, end_alt=alt - cost,
            label=f"{label_prefix} turn 2")
        segments.append(seg)
        pos = GeoPoint(seg.end_lat, seg.end_lon)
        alt -= cost; hdg = seg.end_heading_deg
    return segments, pos, alt, hdg


def _backbone_from_wp(wp_idx: int, waypoints: list[_Waypoint],
                        start_alt: float, pattern_side: str,
                        R_po180: float, best_glide_tas_kt: float,
                        glide_ratio: float, wind_dir_deg: float,
                        wind_speed_kt: float, runway_heading_deg: float,
                        reverse_runway_deg: float,
                        lk_pos_override: Optional[GeoPoint] = None
                        ) -> tuple[list[GlideSegment], float]:
    """Build backbone segments from waypoints[wp_idx] to touchdown.
    `lk_pos_override` lets the caller substitute a different (extended)
    LK position — used when extending downwind to absorb excess alt."""
    segments: list[GlideSegment] = []
    alt = start_alt
    wp_overhead, wp_LK, wp_base, wp_F, wp_TD = waypoints
    # Use the extended LK position if provided AND the leg starts at LK.
    actual_LK = (lk_pos_override if (wp_idx <= 1 and lk_pos_override is not None)
                    else wp_LK.pos)

    if wp_idx <= 0:  # at overhead → glide to LK
        d = _ft(wp_overhead.pos, actual_LK)
        trk = _bearing(wp_overhead.pos, actual_LK)
        cost = _wind_corrected_alt_cost_ft(
            d, trk, best_glide_tas_kt, glide_ratio,
            wind_dir_deg, wind_speed_kt)
        segments.append(_straight_segment(
            wp_overhead.pos, alt, actual_LK, alt - cost,
            label="Overhead → Low Key"))
        alt -= cost

    if wp_idx <= 1:  # at LK → downwind to base
        d = _ft(actual_LK, wp_base.pos)
        cost = _wind_corrected_alt_cost_ft(
            d, reverse_runway_deg, best_glide_tas_kt, glide_ratio,
            wind_dir_deg, wind_speed_kt)
        segments.append(_straight_segment(
            actual_LK, alt, wp_base.pos, alt - cost,
            label="Downwind"))
        alt -= cost

    if wp_idx <= 2:  # at base → PO180 to F
        arc_len = math.pi * R_po180
        cost = arc_len / max(1.0, glide_ratio)
        segments.append(_turn_segment_180(
            start=wp_base.pos, start_alt=alt,
            start_heading=reverse_runway_deg,
            end=wp_F.pos, end_alt=alt - cost,
            end_heading=runway_heading_deg,
            turn_radius_ft=R_po180,
            direction=pattern_side,
            label="PO180 base→final"))
        alt -= cost

    if wp_idx <= 3:  # at F → glide to TD (slip absorbs modest excess)
        # Use wind-corrected glide ratio so the slip-aware cost computation
        # accounts for headwind/tailwind on final.
        cost_normal_wind = _wind_corrected_alt_cost_ft(
            _ft(wp_F.pos, wp_TD.pos), runway_heading_deg,
            best_glide_tas_kt, glide_ratio,
            wind_dir_deg, wind_speed_kt)
        # Equivalent GR-on-ground for the slip helper:
        d = _ft(wp_F.pos, wp_TD.pos)
        gr_effective = d / max(1e-3, cost_normal_wind)
        cost = _final_leg_cost_with_slip(alt, d, gr_effective)
        alt_td = alt - cost   # may be negative if insufficient energy
        segments.append(_straight_segment(
            wp_F.pos, alt, wp_TD.pos, alt_td,
            label="Final → touchdown"))
        alt = alt_td

    return segments, alt


def plan_glide_backbone(*,
                          start_lat: float,
                          start_lon: float,
                          start_alt_agl_ft: float,
                          start_heading_deg: float,
                          touchdown_lat: float,
                          touchdown_lon: float,
                          touchdown_elev_ft: float,
                          runway_heading_deg: float,
                          best_glide_tas_kt: float,
                          glide_ratio: float,
                          max_bank_deg: float = MAX_BANK_DEG,
                          planning_bank_deg: float = PLANNING_BANK_DEG,
                          wind_dir_deg: float = 0.0,
                          wind_speed_kt: float = 0.0,
                          ) -> GlidePlan:
    """Backbone planner. Picks the latest reachable join waypoint, connects
    via Dubins, follows the backbone to touchdown. Tries both pattern sides
    and returns the better plan."""
    start = GeoPoint(start_lat, start_lon)
    touchdown = GeoPoint(touchdown_lat, touchdown_lon)
    planning_bank_deg = min(planning_bank_deg, max_bank_deg)
    R_normal = _turn_radius_ft(best_glide_tas_kt, planning_bank_deg)
    R_po180 = PATTERN_OFFSET_FT / 2.0
    po180_bank_deg = math.degrees(math.atan(
        (best_glide_tas_kt * 1.68781) ** 2 / (G_FPS2 * R_po180)))
    reverse_runway = _wrap_360(runway_heading_deg + 180.0)

    cross_ft, along_ft = _cross_track_along_track_ft(
        touchdown, start, runway_heading_deg)
    on_final_side = along_ft < 0
    direct_dist_ft = _ft(start, touchdown)
    direct_dist_nm = direct_dist_ft / FT_PER_NM
    track_to_td = (_bearing(start, touchdown)
                     if direct_dist_ft > 1e-3 else runway_heading_deg)
    direct_glide_alt_ft = _wind_corrected_alt_cost_ft(
        direct_dist_ft, track_to_td, best_glide_tas_kt,
        glide_ratio, wind_dir_deg, wind_speed_kt)
    arrival_alt_agl = start_alt_agl_ft - direct_glide_alt_ft
    final_wind_component_kt = wind_speed_kt * math.cos(
        math.radians(_angle_diff_deg(wind_dir_deg, runway_heading_deg)))

    def _diag_for(side, wp_name, alt_at_td, **extras):
        return _diagnostics(
            start_alt_msl_ft=start_alt_agl_ft + touchdown_elev_ft,
            start_alt_agl_ft=start_alt_agl_ft,
            direct_dist_nm=direct_dist_nm,
            direct_glide_alt_ft=direct_glide_alt_ft,
            arrival_alt_agl_ft=arrival_alt_agl,
            excess_at_high_key_ft=arrival_alt_agl - HIGH_KEY_AGL_FT,
            excess_at_low_key_ft=arrival_alt_agl - LOW_KEY_AGL_FT,
            pattern_side=side,
            on_final_side=on_final_side,
            best_glide_tas_kt=best_glide_tas_kt,
            glide_ratio=glide_ratio,
            planning_bank_deg=planning_bank_deg,
            max_bank_deg=max_bank_deg,
            turn_radius_ft=R_normal,
            spiral_turns=extras.get('spiral_turns', 0.0),
            spiral_bank_deg=extras.get('spiral_bank_deg', 0.0),
            wind_dir_deg=wind_dir_deg,
            wind_speed_kt=wind_speed_kt,
            final_wind_component_kt=final_wind_component_kt,
            approach_strategy=extras.get('approach_strategy',
                                              f"join_{wp_name}"),
            feasible=extras.get('feasible', True),
            failure_reason=extras.get('failure_reason', None),
        )

    # Off-field check — let the segment's end_alt go negative so the
    # executor can truncate the trajectory at the actual ground-impact
    # point (constant physical sink rate, not the fake-averaged one).
    if arrival_alt_agl < -100.0:
        return GlidePlan(
            segments=[_straight_segment(
                start, start_alt_agl_ft, touchdown, arrival_alt_agl,
                label="Best-effort (won't reach field)")],
            key_positions=[KeyPosition(
                "touchdown", touchdown.latitude, touchdown.longitude,
                0.0, runway_heading_deg)],
            diagnostics=_diag_for(
                "none", "off_field", arrival_alt_agl,
                approach_strategy="off_field", feasible=False,
                failure_reason=(
                    f"{(direct_glide_alt_ft - start_alt_agl_ft):.0f} ft "
                    f"short. Need {direct_glide_alt_ft:.0f} ft AGL; "
                    f"have {start_alt_agl_ft:.0f}.")))

    best_plan = None
    best_score = math.inf

    # Aligned-on-final aircraft can use a wider WP_F margin (slip on
    # final handles modest excess — better than detouring to LK).
    aligned_si = (on_final_side
                    and abs(cross_ft) <= STRAIGHT_IN_MAX_XTRACK_FT)

    for side in ["left", "right"]:
        waypoints = _build_backbone(touchdown, runway_heading_deg, side,
                                       R_po180, glide_ratio)
        wp_idx, arrival_at_wp = _find_join_wp(
            start, start_alt_agl_ft, waypoints, best_glide_tas_kt,
            glide_ratio, wind_dir_deg, wind_speed_kt,
            aligned_straight_in=aligned_si)
        if wp_idx < 0:
            continue
        chosen_wp = waypoints[wp_idx]

        # ENERGY ABSORPTION PRIORITY:
        # 1) For overhead join: variable-radius SPIRAL (R from 30° AOB
        #    tightest to 1/2 SR widest) absorbs first. Pattern stays at
        #    the small default.
        # 2) For LK / base / F join: arrival is already within tolerance.
        # 3) Only if spiral at max R + reasonable turns can't absorb the
        #    full excess do we GROW the pattern (FINAL_LEG up).
        # For LOW-energy cases the pattern can also SHRINK toward 0.
        extra_final_ft = 0.0
        if wp_idx == 1:
            # Aircraft arrived at LK within tolerance — small final/
            # downwind shrink/grow to match exactly.
            delta_ft = ((arrival_at_wp - chosen_wp.ideal_alt_agl_ft)
                          * glide_ratio / 2.0)
            extra_final_ft = max(
                -FINAL_LEG_FT,
                min(FINAL_LEG_MAX_EXTENSION_FT, delta_ft))
            if abs(extra_final_ft) > 50.0:
                new_final_leg = max(
                    0.0, FINAL_LEG_FT + extra_final_ft)
                waypoints = _build_backbone(
                    touchdown, runway_heading_deg, side,
                    R_po180, glide_ratio,
                    final_leg_ft=new_final_leg)
                chosen_wp = waypoints[wp_idx]
        # For wp_idx == 0 (overhead), do NOT pre-grow pattern. The orbit
        # branch below handles it via variable spiral radius. Pattern
        # growth only happens if the spiral at max R hits its turn cap.

        # If we're joining at LK and STILL have excess beyond what the
        # grown pattern absorbs (= final extension hit the cap), shift
        # LK upwind for the remaining downwind extension.
        target_pos = chosen_wp.pos
        target_heading = chosen_wp.heading_into_deg
        downwind_extension_ft = 0.0
        if wp_idx == 1:
            remaining_excess = max(
                0.0, arrival_at_wp - chosen_wp.ideal_alt_agl_ft)
            downwind_extension_ft = min(
                MAX_DOWNWIND_EXTENSION_FT,
                remaining_excess * glide_ratio)
            if downwind_extension_ft > 50.0:
                target_pos = _point_at_bearing(
                    chosen_wp.pos, runway_heading_deg,
                    downwind_extension_ft)

        # Build smooth connection. Force all entry turns to match pattern
        # side so the trajectory is a single direction of turn end-to-end
        # (no flip-flop between LEFT and RIGHT).
        conn_segments, conn_pos, conn_alt, conn_hdg = _connect_via_dubins(
            start, start_alt_agl_ft, start_heading_deg,
            target_pos, target_heading,
            R_normal, best_glide_tas_kt, glide_ratio,
            wind_dir_deg, wind_speed_kt, label_prefix="Entry",
            force_direction=side)

        orbit_n_turns = 0.0
        orbit_bank = po180_bank_deg

        if wp_idx == 0:
            # Joining at overhead means we orbit to bleed altitude. The
            # orbit is positioned so its circumference passes EXACTLY
            # through low-key (PO180 start), tangent to the downwind
            # heading. That way the spiral exits tangent to downwind —
            # no kink between orbit and the backbone.
            side_sign_local = -1 if side == "left" else +1
            center_bearing_from_lk = _wrap_360(
                reverse_runway + side_sign_local * 90.0)

            # DYNAMIC SPIRAL RADIUS: scale R with altitude excess so the
            # spiral absorbs the energy. When excess is large, "split the
            # difference" — use multiple MEDIUM spirals at uniform R
            # instead of one big + one tight.
            #
            # Tightest R = 30° AOB (R_min).
            # Widest R = 1/2 standard rate (R_max_user), capped by
            #   PATTERN_OFFSET so the orbit geometrically fits.
            #
            # Algorithm: estimate the integer N_int needed for the excess
            # to fit at R_max (= ceil(excess/(2π·R_max/GR) − 0.5),
            # assuming ~0.5 fractional turn for geometric closure). Then
            # set R so N_total turns at R exactly absorb the excess —
            # this gives uniform "medium" spirals when N_int > 0.
            target_alt_at_lk_default = waypoints[1].ideal_alt_agl_ft
            est_excess = max(
                50.0, arrival_at_wp - target_alt_at_lk_default)
            R_min_orbit = _turn_radius_ft(
                best_glide_tas_kt, SPIRAL_BANK_MAX_DEG)
            R_max_user = ((best_glide_tas_kt * 1.68781)
                              / math.radians(SPIRAL_RATE_MIN_DEG_PER_S))
            R_max_orbit = min(R_max_user, PATTERN_OFFSET_FT)
            # Integer turns needed at R_max to absorb the excess (with a
            # ~0.5 turn closure assumption).
            n_min_at_Rmax = (est_excess * glide_ratio
                                / (2.0 * math.pi * R_max_orbit))
            n_int_target = max(0, int(math.ceil(n_min_at_Rmax - 0.5)))
            n_total_target = n_int_target + 0.5
            # R that absorbs `est_excess` in `n_total_target` uniform turns.
            R_target = (est_excess * glide_ratio
                          / (2.0 * math.pi * n_total_target)
                          if n_total_target > 0 else R_max_orbit)
            R_orbit = max(R_min_orbit, min(R_max_orbit, R_target))
            orbit_center = _point_at_bearing(
                waypoints[1].pos, center_bearing_from_lk, R_orbit)
            # Tangent from start (= original aircraft pos, before Dubins
            # connection) to the orbit. Two tangents exist; pick the one
            # whose direction is consistent with the spiral direction.
            d_start_to_oc = _ft(start, orbit_center)
            if d_start_to_oc > R_orbit + 100.0:
                alpha_deg = math.degrees(math.asin(
                    R_orbit / max(1.0, d_start_to_oc)))
                sc_bearing = _bearing(start, orbit_center)
                # LEFT (CCW, sign=-1): tangent_bearing = sc + alpha
                # RIGHT (CW, sign=+1): tangent_bearing = sc - alpha
                tangent_bearing = _wrap_360(
                    sc_bearing - side_sign_local * alpha_deg)
                tangent_dist = math.sqrt(
                    d_start_to_oc * d_start_to_oc
                    - R_orbit * R_orbit)
                tangent_point = _point_at_bearing(
                    start, tangent_bearing, tangent_dist)

                # Rebuild connection: Dubins from (start, start_heading)
                # to (tangent_point, tangent_bearing). This kills the
                # already-built conn_segments (which targeted overhead).
                conn_segments, conn_pos, conn_alt, conn_hdg = \
                    _connect_via_dubins(
                        start, start_alt_agl_ft, start_heading_deg,
                        tangent_point, tangent_bearing, R_normal,
                        best_glide_tas_kt, glide_ratio,
                        wind_dir_deg, wind_speed_kt,
                        label_prefix="Orbit entry",
                        force_direction=side)

                # Spiral around orbit_center from tangent_point heading
                # tangent_bearing → exits at low_key heading
                # reverse_runway. N turns = integer + fractional, where
                # fractional makes the geometry close (exit at LK).
                R_orbit_local = R_orbit
                orbit_bank = math.degrees(math.atan(
                    (best_glide_tas_kt * 1.68781) ** 2
                    / (G_FPS2 * R_orbit_local)))
                B_entry = _bearing(orbit_center, tangent_point)
                B_lk = _bearing(orbit_center, waypoints[1].pos)
                # Fractional turns from B_entry to B_lk in spiral direction
                if side_sign_local < 0:  # CCW
                    n_frac = ((B_entry - B_lk) % 360.0) / 360.0
                else:  # CW
                    n_frac = ((B_lk - B_entry) % 360.0) / 360.0
                # Integer turns from altitude need
                spiral_alt_per_turn = ((2.0 * math.pi * R_orbit_local)
                                          / max(1.0, glide_ratio))
                target_alt_at_lk = waypoints[1].ideal_alt_agl_ft
                excess_to_bleed = max(0.0, conn_alt - target_alt_at_lk)
                n_alt = excess_to_bleed / max(1.0, spiral_alt_per_turn)
                # n_int chosen so n_int + n_frac is as close to n_alt as possible
                n_int = max(0, round(n_alt - n_frac))
                orbit_n_turns = n_int + n_frac
                # At least the fractional turn so we end on low_key
                if orbit_n_turns < n_frac:
                    orbit_n_turns = n_frac
                orbit_n_turns = min(ORBIT_MAX_TURNS, orbit_n_turns)
                alt_after_orbit = (conn_alt
                                     - orbit_n_turns
                                     * spiral_alt_per_turn)
                if orbit_n_turns > 0.01:
                    spiral_seg = _spiral_segment(
                        center=orbit_center,
                        start_alt=conn_alt, end_alt=alt_after_orbit,
                        turn_radius_ft=R_orbit_local,
                        n_turns=orbit_n_turns,
                        bank_deg=orbit_bank, direction=side,
                        start_heading=conn_hdg,
                        label=f"Overhead orbit ({orbit_n_turns:.2f} turns)")
                    conn_segments.append(spiral_seg)
                    conn_pos = GeoPoint(spiral_seg.end_lat,
                                           spiral_seg.end_lon)
                    conn_alt = alt_after_orbit
                    conn_hdg = spiral_seg.end_heading_deg
                # After orbit, aircraft is at low_key heading
                # reverse_runway. Backbone continues from LK (wp_idx=1).
                wp_idx_for_backbone = 1
            else:
                # Aircraft too close to orbit center to compute tangent —
                # rare. Fall through to backbone from overhead with a
                # simple straight glide overhead → LK.
                wp_idx_for_backbone = wp_idx
        else:
            wp_idx_for_backbone = wp_idx

        # Follow the backbone from the chosen WP to touchdown. Pass the
        # extended LK position so the downwind leg is correctly lengthened
        # when wp_idx == 1 used a downwind extension.
        lk_pos_for_bb = (target_pos
                            if (wp_idx == 1 and downwind_extension_ft > 50.0)
                            else None)
        bb_segments, alt_at_td = _backbone_from_wp(
            wp_idx_for_backbone, waypoints, conn_alt, side, R_po180,
            best_glide_tas_kt, glide_ratio,
            wind_dir_deg, wind_speed_kt,
            runway_heading_deg, reverse_runway,
            lk_pos_override=lk_pos_for_bb)

        all_segments = conn_segments + bb_segments
        # Score: prefer arrivals close to 0 ft AGL; penalize being high
        # (lands long) more than slightly low.
        score = abs(alt_at_td) + (50.0 if alt_at_td > 50.0 else 0.0)

        if score < best_score:
            best_score = score
            key_positions = [
                KeyPosition("touchdown", touchdown.latitude,
                              touchdown.longitude, 0.0, runway_heading_deg),
                KeyPosition("F", waypoints[3].pos.latitude,
                              waypoints[3].pos.longitude,
                              waypoints[3].ideal_alt_agl_ft,
                              waypoints[3].heading_into_deg),
                KeyPosition("base", waypoints[2].pos.latitude,
                              waypoints[2].pos.longitude,
                              waypoints[2].ideal_alt_agl_ft,
                              waypoints[2].heading_into_deg),
                KeyPosition("low_key", waypoints[1].pos.latitude,
                              waypoints[1].pos.longitude,
                              waypoints[1].ideal_alt_agl_ft,
                              waypoints[1].heading_into_deg),
                KeyPosition("overhead", waypoints[0].pos.latitude,
                              waypoints[0].pos.longitude,
                              waypoints[0].ideal_alt_agl_ft,
                              waypoints[0].heading_into_deg),
            ]
            best_plan = GlidePlan(
                segments=all_segments,
                key_positions=key_positions,
                diagnostics=_diag_for(
                    side, chosen_wp.name, alt_at_td,
                    approach_strategy=f"join_{chosen_wp.name}",
                    spiral_turns=orbit_n_turns,
                    spiral_bank_deg=(orbit_bank if orbit_n_turns > 0
                                       else po180_bank_deg),
                    feasible=(alt_at_td <= 100.0),
                    failure_reason=(
                        None if alt_at_td <= 100.0
                        else f"Arrives {alt_at_td:.0f} ft high; slip or "
                              f"S-turn on final to bleed.")),
            )

    if best_plan is None:
        return GlidePlan(
            segments=[_straight_segment(
                start, start_alt_agl_ft, touchdown, 0.0,
                label="Best-effort")],
            key_positions=[KeyPosition(
                "touchdown", touchdown.latitude, touchdown.longitude,
                0.0, runway_heading_deg)],
            diagnostics=_diag_for(
                "none", "none", arrival_alt_agl,
                approach_strategy="off_field", feasible=False,
                failure_reason="Could not build plan."))

    return best_plan


# =============================================================================
# Path-intercept planner — the aircraft intercepts the IDEAL PO180 path
# (downwind → continuous 180° → final) at whatever point its energy
# allows. The ideal path is parametrized by arc length `s` measured
# backward from touchdown. For each `s`, the aircraft must fly:
#   dist(start, point_at_s) + s   <= start_alt * GR
# The latest reachable `s` is the optimal intercept.
# =============================================================================


def _ideal_path_point_at_s(s: float, touchdown: GeoPoint,
                            runway_heading_deg: float, pattern_side: str,
                            R_po180: float
                            ) -> tuple[GeoPoint, float]:
    """Position + heading-at-position along the IDEAL PO180 path,
    parametrized by arc length `s` measured backward from TD.

    Segments:
      s in [0, FL]          → final leg (heading runway)
      s in [FL, FL+πR]      → PO180 arc
      s in [FL+πR, 2FL+πR]  → downwind (heading reverse_runway)
      s >  2FL+πR           → extended downwind (still heading reverse_runway)
    """
    sign = -1 if pattern_side == "left" else +1
    reverse_runway = _wrap_360(runway_heading_deg + 180.0)
    perp_to_pattern = _wrap_360(runway_heading_deg + sign * 90.0)
    FL = FINAL_LEG_FT
    arc_len = math.pi * R_po180

    if s <= FL:
        # Final leg
        pos = _point_at_bearing(touchdown, reverse_runway, s)
        return pos, runway_heading_deg

    s2 = s - FL
    if s2 <= arc_len:
        # PO180 arc
        F_pos = _point_at_bearing(touchdown, reverse_runway, FL)
        center = _point_at_bearing(F_pos, perp_to_pattern, R_po180)
        # Bearing from center to F = perp_from_pattern (opposite of perp_to_pattern)
        # Walking backward along PO180 (= going time-forward direction is from
        # base_entry to F = pattern_side turn direction). Backward from F:
        #   LEFT pattern (forward CCW): backward CW → bearing INCREASES
        #   RIGHT pattern (forward CW): backward CCW → bearing DECREASES
        sign_backward = +1.0 if pattern_side == "left" else -1.0
        perp_from_pattern = _wrap_360(perp_to_pattern + 180.0)
        theta_deg = math.degrees(s2 / R_po180)
        bearing_at_s = _wrap_360(
            perp_from_pattern + sign_backward * theta_deg)
        pos = _point_at_bearing(center, bearing_at_s, R_po180)
        # Heading (forward of motion at this point) rotates from
        # runway_heading (at F) toward reverse_runway (at base_entry).
        heading_at_s = _wrap_360(
            runway_heading_deg + sign_backward * theta_deg)
        return pos, heading_at_s

    s3 = s - FL - arc_len
    # Downwind from base_entry (s=FL+arc_len) to LK (s=2FL+arc_len), and
    # extended downwind beyond LK (s > 2FL+arc_len).
    base_entry = _point_at_bearing(touchdown, reverse_runway, FL)
    base_entry = _point_at_bearing(base_entry, perp_to_pattern,
                                       2.0 * R_po180)
    # Walking backward from base_entry toward LK in the runway-heading
    # direction (= upwind), then continues past LK.
    pos = _point_at_bearing(base_entry, runway_heading_deg, s3)
    return pos, reverse_runway


def _find_intercept_on_ideal_path(start: GeoPoint, start_alt_agl_ft: float,
                                     start_heading_deg: float,
                                     touchdown: GeoPoint,
                                     runway_heading_deg: float,
                                     pattern_side: str, R_po180: float,
                                     R_normal: float,
                                     glide_ratio: float,
                                     best_glide_tas_kt: float,
                                     wind_dir_deg: float,
                                     wind_speed_kt: float,
                                     max_extended_downwind_ft: float,
                                     ) -> tuple[float, GeoPoint, float]:
    """Find the latest arc-length `s` on the ideal path that the aircraft
    can reach with its altitude budget. The Dubins entry path is what the
    executor will actually fly, so its length must be used (not the
    straight-line distance from start to the intercept point — those can
    differ significantly when the heading change is large).

    Returns (s, intercept_pos, intercept_heading), or (-1, None, 0) when
    no point on the ideal path is reachable."""
    FL = FINAL_LEG_FT
    arc_len = math.pi * R_po180
    max_s = 2.0 * FL + arc_len + max_extended_downwind_ft
    DS = 100.0
    n_steps = int(max_s / DS) + 1

    best_s = -1.0
    best_pos = None
    best_hdg = 0.0
    for i in range(n_steps + 1):
        s = i * DS
        pos, hdg = _ideal_path_point_at_s(
            s, touchdown, runway_heading_deg, pattern_side, R_po180)
        # Dubins entry length — try both LSL and RSR, use the shorter.
        d_lsl = _dubins_csc(start, start_heading_deg, pos, hdg,
                                R_normal, "left")
        d_rsr = _dubins_csc(start, start_heading_deg, pos, hdg,
                                R_normal, "right")
        len_l = (math.radians(d_lsl[0]) * R_normal + d_lsl[1]
                   + math.radians(d_lsl[2]) * R_normal) if d_lsl else math.inf
        len_r = (math.radians(d_rsr[0]) * R_normal + d_rsr[1]
                   + math.radians(d_rsr[2]) * R_normal) if d_rsr else math.inf
        entry_dist = min(len_l, len_r)
        if not math.isfinite(entry_dist):
            # Fallback to direct dist (rare — both circles degenerate).
            entry_dist = _ft(start, pos)
        # Wind: use the straight segment of the Dubins for wind correction
        # (the turns net out to zero in calm wind; in wind they're a few %
        # — accept the approximation).
        straight_d = min(d_lsl[1] if d_lsl else 0.0,
                            d_rsr[1] if d_rsr else 0.0)
        if straight_d > 1e-3 and (d_lsl is not None or d_rsr is not None):
            tangent_pt = (d_lsl[4] if (d_lsl and len_l <= len_r)
                            else (d_rsr[4] if d_rsr else None))
            trk = (_bearing(start, tangent_pt)
                     if tangent_pt is not None else hdg)
            entry_cost_wind = _wind_corrected_alt_cost_ft(
                entry_dist, trk, best_glide_tas_kt, glide_ratio,
                wind_dir_deg, wind_speed_kt)
        else:
            entry_cost_wind = entry_dist / max(1.0, glide_ratio)
        on_path_cost = s / max(1.0, glide_ratio)
        total_alt_needed = entry_cost_wind + on_path_cost
        if total_alt_needed <= start_alt_agl_ft:
            best_s = s
            best_pos = pos
            best_hdg = hdg
    if best_s < 0:
        return -1.0, None, 0.0
    return best_s, best_pos, best_hdg


def _build_segments_along_ideal_path(intercept_s: float,
                                        intercept_alt: float,
                                        touchdown: GeoPoint,
                                        runway_heading_deg: float,
                                        pattern_side: str,
                                        R_po180: float,
                                        best_glide_tas_kt: float,
                                        glide_ratio: float,
                                        wind_dir_deg: float,
                                        wind_speed_kt: float,
                                        ) -> tuple[list[GlideSegment], float]:
    """From the intercept point at `intercept_s`, build segments that
    follow the ideal path forward (s decreasing) to touchdown. Returns
    (segments, alt_at_TD).

    Slip on the final leg absorbs modest excess (per
    _final_leg_cost_with_slip).
    """
    segments: list[GlideSegment] = []
    FL = FINAL_LEG_FT
    arc_len = math.pi * R_po180
    sign = -1 if pattern_side == "left" else +1
    reverse_runway = _wrap_360(runway_heading_deg + 180.0)
    perp_to_pattern = _wrap_360(runway_heading_deg + sign * 90.0)

    # Key positions
    F_pos = _point_at_bearing(touchdown, reverse_runway, FL)
    base_entry = _point_at_bearing(F_pos, perp_to_pattern, 2.0 * R_po180)
    LK_pos = _point_at_bearing(touchdown, perp_to_pattern, 2.0 * R_po180)
    intercept_pos, _ = _ideal_path_point_at_s(
        intercept_s, touchdown, runway_heading_deg, pattern_side, R_po180)

    alt = intercept_alt
    s = intercept_s

    # If intercept on extended downwind: glide downwind from intercept
    # back to LK (= along=0).
    if s > 2.0 * FL + arc_len:
        ds_ext = s - (2.0 * FL + arc_len)
        cost = _wind_corrected_alt_cost_ft(
            ds_ext, reverse_runway, best_glide_tas_kt, glide_ratio,
            wind_dir_deg, wind_speed_kt)
        segments.append(_straight_segment(
            intercept_pos, alt, LK_pos, alt - cost,
            label="Extended downwind"))
        alt -= cost
        s = 2.0 * FL + arc_len

    # If still on downwind (s in [FL+arc_len, 2FL+arc_len]): fly the rest
    # of downwind to base_entry.
    if s > FL + arc_len:
        ds3 = s - (FL + arc_len)
        # ds3 = remaining downwind from current point to base_entry
        cur_pos, _ = _ideal_path_point_at_s(
            s, touchdown, runway_heading_deg, pattern_side, R_po180)
        cost = _wind_corrected_alt_cost_ft(
            ds3, reverse_runway, best_glide_tas_kt, glide_ratio,
            wind_dir_deg, wind_speed_kt)
        segments.append(_straight_segment(
            cur_pos, alt, base_entry, alt - cost,
            label="Downwind"))
        alt -= cost
        s = FL + arc_len

    # If still on PO180 arc (s in [FL, FL+arc_len]): fly the rest of the
    # arc to F.
    if s > FL:
        # Partial PO180 from current point to F.
        s2 = s - FL  # arc length remaining on PO180
        arc_angle_deg = math.degrees(s2 / R_po180)
        cur_pos, cur_hdg = _ideal_path_point_at_s(
            s, touchdown, runway_heading_deg, pattern_side, R_po180)
        # Direction of the forward turn matches pattern_side.
        arc_alt_cost = s2 / max(1.0, glide_ratio)
        segments.append(_turn_segment_n(
            start=cur_pos, start_alt=alt,
            start_heading=cur_hdg,
            turn_angle_deg=arc_angle_deg,
            turn_radius_ft=R_po180,
            direction=pattern_side,
            end_alt=alt - arc_alt_cost,
            label=("PO180 base→final" if abs(arc_angle_deg - 180.0) < 0.5
                     else f"PO180 partial ({arc_angle_deg:.0f}°)")))
        alt -= arc_alt_cost
        s = FL

    # Final leg from F to TD. Slip absorbs modest excess.
    cost_normal_wind = _wind_corrected_alt_cost_ft(
        FL, runway_heading_deg, best_glide_tas_kt, glide_ratio,
        wind_dir_deg, wind_speed_kt)
    gr_effective_final = FL / max(1e-3, cost_normal_wind)
    cost_final = _final_leg_cost_with_slip(alt, FL, gr_effective_final)
    alt_at_td = alt - cost_final
    segments.append(_straight_segment(
        F_pos, alt, touchdown, alt_at_td, label="Final → touchdown"))
    return segments, alt_at_td


def plan_glide_intercept(*,
                            start_lat: float,
                            start_lon: float,
                            start_alt_agl_ft: float,
                            start_heading_deg: float,
                            touchdown_lat: float,
                            touchdown_lon: float,
                            touchdown_elev_ft: float,
                            runway_heading_deg: float,
                            best_glide_tas_kt: float,
                            glide_ratio: float,
                            max_bank_deg: float = MAX_BANK_DEG,
                            planning_bank_deg: float = PLANNING_BANK_DEG,
                            wind_dir_deg: float = 0.0,
                            wind_speed_kt: float = 0.0,
                            ) -> GlidePlan:
    """Plan the engine-out glide by intercepting the IDEAL PO180 path at
    the latest reachable point given the aircraft's energy."""
    start = GeoPoint(start_lat, start_lon)
    touchdown = GeoPoint(touchdown_lat, touchdown_lon)
    planning_bank_deg = min(planning_bank_deg, max_bank_deg)
    R_normal = _turn_radius_ft(best_glide_tas_kt, planning_bank_deg)
    R_po180 = PATTERN_OFFSET_FT / 2.0
    reverse_runway = _wrap_360(runway_heading_deg + 180.0)
    final_wind_component_kt = wind_speed_kt * math.cos(
        math.radians(_angle_diff_deg(wind_dir_deg, runway_heading_deg)))

    cross_ft, along_ft = _cross_track_along_track_ft(
        touchdown, start, runway_heading_deg)
    on_final_side = along_ft < 0
    direct_dist_ft = _ft(start, touchdown)
    direct_dist_nm = direct_dist_ft / FT_PER_NM
    track_to_td = (_bearing(start, touchdown)
                     if direct_dist_ft > 1e-3 else runway_heading_deg)
    direct_glide_alt_ft = _wind_corrected_alt_cost_ft(
        direct_dist_ft, track_to_td, best_glide_tas_kt,
        glide_ratio, wind_dir_deg, wind_speed_kt)
    arrival_alt_agl = start_alt_agl_ft - direct_glide_alt_ft

    def _diag_for(side, strategy, alt_at_td, **extras):
        d = dict(
            start_alt_msl_ft=start_alt_agl_ft + touchdown_elev_ft,
            start_alt_agl_ft=start_alt_agl_ft,
            direct_dist_nm=direct_dist_nm,
            direct_glide_alt_ft=direct_glide_alt_ft,
            arrival_alt_agl_ft=arrival_alt_agl,
            excess_at_high_key_ft=arrival_alt_agl - HIGH_KEY_AGL_FT,
            excess_at_low_key_ft=arrival_alt_agl - LOW_KEY_AGL_FT,
            pattern_side=side,
            on_final_side=on_final_side,
            best_glide_tas_kt=best_glide_tas_kt,
            glide_ratio=glide_ratio,
            planning_bank_deg=planning_bank_deg,
            max_bank_deg=max_bank_deg,
            turn_radius_ft=R_normal,
            spiral_turns=extras.get('spiral_turns', 0.0),
            spiral_bank_deg=extras.get('spiral_bank_deg', 0.0),
            wind_dir_deg=wind_dir_deg,
            wind_speed_kt=wind_speed_kt,
            final_wind_component_kt=final_wind_component_kt,
            approach_strategy=strategy,
            feasible=extras.get('feasible', True),
            failure_reason=extras.get('failure_reason', None),
        )
        return _diagnostics(**d)

    best_plan = None
    best_score = math.inf

    for side in ["left", "right"]:
        intercept_s, intercept_pos, intercept_heading = \
            _find_intercept_on_ideal_path(
                start, start_alt_agl_ft, start_heading_deg,
                touchdown, runway_heading_deg,
                side, R_po180, R_normal,
                glide_ratio, best_glide_tas_kt,
                wind_dir_deg, wind_speed_kt,
                MAX_DOWNWIND_EXTENSION_FT)

        if intercept_s < 0:
            # Can't reach any point on the ideal path — best-effort
            # straight glide; executor truncates at impact.
            failure_seg = _straight_segment(
                start, start_alt_agl_ft, touchdown,
                arrival_alt_agl,
                label="Best-effort (won't reach ideal path)")
            candidate = GlidePlan(
                segments=[failure_seg],
                key_positions=[KeyPosition(
                    "touchdown", touchdown.latitude, touchdown.longitude,
                    0.0, runway_heading_deg)],
                diagnostics=_diag_for(
                    side, "off_field", arrival_alt_agl,
                    feasible=False,
                    failure_reason=(
                        f"{(direct_glide_alt_ft - start_alt_agl_ft):.0f} "
                        f"ft short.")))
            score = abs(arrival_alt_agl) + 10000.0  # heavy penalty
            if score < best_score:
                best_score = score
                best_plan = candidate
            continue

        # Dubins from (start, start_heading) to (intercept_pos,
        # intercept_heading). force_direction = pattern_side with soft cap.
        conn_segments, conn_pos, conn_alt, conn_hdg = _connect_via_dubins(
            start, start_alt_agl_ft, start_heading_deg,
            intercept_pos, intercept_heading,
            R_normal, best_glide_tas_kt, glide_ratio,
            wind_dir_deg, wind_speed_kt, label_prefix="Entry",
            force_direction=side)

        # Build segments along the ideal path from intercept to TD.
        path_segments, alt_at_td = _build_segments_along_ideal_path(
            intercept_s, conn_alt, touchdown, runway_heading_deg,
            side, R_po180, best_glide_tas_kt, glide_ratio,
            wind_dir_deg, wind_speed_kt)

        # Spiral absorption: if alt_at_td is still positive, the ideal
        # path was capped (we hit the downwind-extension limit) and slip
        # alone couldn't burn the rest. Insert a constant-radius spiral
        # at the engine-out position so the aircraft arrives at F with
        # alt that slip can fully absorb (= cost_max_slip).
        spiral_segments: list[GlideSegment] = []
        if alt_at_td > 50.0:
            absorb_target = alt_at_td
            tas_fps = best_glide_tas_kt * 1.68781
            R_spiral_min = (tas_fps * tas_fps) / (
                32.174 * math.tan(math.radians(SPIRAL_BANK_MAX_DEG)))
            R_spiral_max = tas_fps / math.radians(
                SPIRAL_RATE_MIN_DEG_PER_S)
            # Pick smallest n (full turns) with R in valid range.
            absorb_per_turn_at_min_R = (
                2.0 * math.pi * R_spiral_min / max(1.0, glide_ratio))
            R_spiral = None
            n_turns_spiral = 0
            if absorb_target >= absorb_per_turn_at_min_R:
                for n in range(1, 8):
                    R_candidate = (absorb_target * glide_ratio
                                       / (2.0 * math.pi * n))
                    if R_spiral_min <= R_candidate <= R_spiral_max:
                        R_spiral = R_candidate
                        n_turns_spiral = n
                        break
                if R_spiral is None:
                    # Too much energy for our R range — saturate at R_max
                    # with as many turns as fit.
                    n_turns_spiral = max(1, int(math.ceil(
                        absorb_target * glide_ratio
                        / (2.0 * math.pi * R_spiral_max))))
                    R_spiral = (absorb_target * glide_ratio
                                   / (2.0 * math.pi * n_turns_spiral))
                    R_spiral = max(R_spiral_min,
                                       min(R_spiral_max, R_spiral))
            if R_spiral is not None and n_turns_spiral > 0:
                # Center perpendicular to start_heading on the pattern
                # side (so the spiral turns the same direction as the
                # pattern and the Dubins entry).
                sign = -1.0 if side == "left" else 1.0
                center_bearing = _wrap_360(start_heading_deg - sign * 90.0)
                spiral_center = _point_at_bearing(
                    start, center_bearing, R_spiral)
                spiral_absorb_ft = (n_turns_spiral * 2.0 * math.pi
                                          * R_spiral / glide_ratio)
                spiral_seg = _spiral_segment(
                    center=spiral_center,
                    start_alt=start_alt_agl_ft,
                    end_alt=start_alt_agl_ft - spiral_absorb_ft,
                    turn_radius_ft=R_spiral,
                    n_turns=float(n_turns_spiral),
                    bank_deg=math.degrees(math.atan(
                        tas_fps * tas_fps
                        / (32.174 * R_spiral))),
                    direction=side,
                    start_heading=start_heading_deg,
                    label=(f"Spiral absorb ({n_turns_spiral}×, "
                             f"R={R_spiral:.0f}ft)"))
                spiral_segments.append(spiral_seg)
                # Re-run the entry + ideal-path build with the reduced
                # start altitude.
                conn_segments, conn_pos, conn_alt, conn_hdg = \
                    _connect_via_dubins(
                        start,
                        start_alt_agl_ft - spiral_absorb_ft,
                        start_heading_deg,
                        intercept_pos, intercept_heading,
                        R_normal, best_glide_tas_kt, glide_ratio,
                        wind_dir_deg, wind_speed_kt, label_prefix="Entry",
                        force_direction=side)
                path_segments, alt_at_td = \
                    _build_segments_along_ideal_path(
                        intercept_s, conn_alt, touchdown,
                        runway_heading_deg, side, R_po180,
                        best_glide_tas_kt, glide_ratio,
                        wind_dir_deg, wind_speed_kt)

        all_segments = spiral_segments + conn_segments + path_segments

        # Score: closer to landing at 0 is better; penalize overshoots.
        score = abs(alt_at_td)
        if alt_at_td > 100.0:
            score += alt_at_td  # extra penalty for high arrival

        if score < best_score:
            best_score = score
            FL = FINAL_LEG_FT
            arc_len = math.pi * R_po180
            F_pos = _point_at_bearing(touchdown, reverse_runway, FL)
            LK_pos = _point_at_bearing(touchdown,
                                            _wrap_360(runway_heading_deg
                                                     + (-1 if side == "left"
                                                         else 1) * 90),
                                            2.0 * R_po180)
            key_positions = [
                KeyPosition("touchdown", touchdown.latitude,
                              touchdown.longitude, 0.0, runway_heading_deg),
                KeyPosition("F", F_pos.latitude, F_pos.longitude,
                              FL / glide_ratio, runway_heading_deg),
                KeyPosition("low_key", LK_pos.latitude, LK_pos.longitude,
                              (2 * FL + arc_len) / glide_ratio,
                              reverse_runway),
                KeyPosition("intercept", intercept_pos.latitude,
                              intercept_pos.longitude,
                              conn_alt, intercept_heading),
            ]
            best_plan = GlidePlan(
                segments=all_segments,
                key_positions=key_positions,
                diagnostics=_diag_for(
                    side, "intercept_path", alt_at_td,
                    feasible=(alt_at_td <= 50.0),
                    failure_reason=(
                        None if alt_at_td <= 50.0
                        else f"Arrives {alt_at_td:.0f} ft high.")),
            )

    if best_plan is None:
        # Should never happen — fallback
        return GlidePlan(
            segments=[_straight_segment(
                start, start_alt_agl_ft, touchdown, arrival_alt_agl,
                label="Best-effort")],
            key_positions=[KeyPosition(
                "touchdown", touchdown.latitude, touchdown.longitude,
                0.0, runway_heading_deg)],
            diagnostics=_diag_for(
                "none", "off_field", arrival_alt_agl,
                feasible=False, failure_reason="Could not build plan."))

    return best_plan


def simulate_engineout_planned(*,
                                  start_point,
                                  start_heading: float,
                                  touchdown_point,
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
                                  wind_profile=None,
                                  altitude_agl: float,
                                  touchdown_elev_ft: float,
                                  max_bank_deg: float = MAX_BANK_DEG,
                                  reaction_sec: float = 2.0,
                                  speed_tau_sec: float = 4.0,
                                  bank_tau_sec: float = 1.5,
                                  timestep_sec: float = 0.5,
                                  ) -> tuple[list, list, dict]:
    """Plan + execute an engine-out glide. Returns the legacy
    (path, hover_data, meta) triple the existing engineout callback expects.

    This wraps `plan_glide` (geometric trajectory planner) +
    `simulation.eo_executor.execute_plan` (forward integrator) into the
    same interface as the old `simulate_engineout_glide`, so callers can
    swap them without touching downstream code (map render, scrubber,
    results modal)."""
    from .base import _get_best_glide_and_ratio
    from .eo_executor import execute_plan
    from physics.atmosphere import (
        compute_pressure_altitude, compute_air_density,
        adjust_glide_ratio_for_density,
    )
    from physics.aerodynamics import compute_true_airspeed

    ac_local = dict(ac)
    ac_local["total_weight_lb"] = float(weight_lbs)

    bg_kias, base_glide_ratio = _get_best_glide_and_ratio(
        ac_local, engine_option, flap_config, prop_config)

    # Atmosphere — TAS at mid-glide altitude (rough approximation; planner
    # is not sensitive to this at the few-percent level).
    mid_msl_ft = (touchdown_elev_ft +
                   touchdown_elev_ft + altitude_agl) / 2.0  # mid of (td, start)
    press_alt_ft = compute_pressure_altitude(mid_msl_ft, altimeter_inhg)
    rho = compute_air_density(press_alt_ft, oat_c)
    bg_ktas = compute_true_airspeed(bg_kias, press_alt_ft, oat_c)
    glide_ratio_eff = adjust_glide_ratio_for_density(base_glide_ratio, rho)

    plan = plan_glide_intercept(
        start_lat=start_point.latitude,
        start_lon=start_point.longitude,
        start_alt_agl_ft=float(altitude_agl),
        start_heading_deg=float(start_heading),
        touchdown_lat=touchdown_point.latitude,
        touchdown_lon=touchdown_point.longitude,
        touchdown_elev_ft=float(touchdown_elev_ft),
        runway_heading_deg=float(touchdown_heading),
        best_glide_tas_kt=float(bg_ktas),
        glide_ratio=float(glide_ratio_eff),
        max_bank_deg=float(max_bank_deg),
        planning_bank_deg=min(float(PLANNING_BANK_DEG), float(max_bank_deg)),
        wind_dir_deg=float(wind_dir),
        wind_speed_kt=float(wind_speed),
    )

    path, hover_data, meta = execute_plan(
        plan,
        tas_kt=float(bg_ktas),
        wind_dir_deg=float(wind_dir),
        wind_speed_kt=float(wind_speed),
        dt_sec=float(timestep_sec),
        touchdown_elev_ft=float(touchdown_elev_ft),
        start_heading_deg=float(start_heading),
    )

    # Legacy callers expect `success`, `impact_point`, `reason`,
    # `turn_direction` at the top of meta. Map them off the diagnostics.
    d = plan.diagnostics
    meta["success"] = bool(d.feasible)
    meta["turn_direction"] = d.pattern_side
    if not d.feasible:
        # Best-effort end-of-path = impact point (last sample on the map)
        if path:
            meta["impact_point"] = (path[-1][0], path[-1][1])
        meta["reason"] = d.failure_reason or "unreachable"

    # Best-glide context the info panel still wants
    meta["best_glide_tas_kt"] = bg_ktas
    meta["best_glide_ias_kt"] = bg_kias
    meta["glide_ratio"] = glide_ratio_eff

    return path, hover_data, meta


def _diagnostics(**kwargs) -> GlideDiagnostics:
    """Build a GlideDiagnostics with the retrospective fields filled in."""
    # Compute the retrospective:
    #   required_alt_agl_to_make_it = direct_glide_alt + LOW_KEY + base_to_final
    #     arc altitude + short_final altitude.
    glide_ratio = kwargs["glide_ratio"]
    turn_radius_ft = kwargs["turn_radius_ft"]
    direct_glide_alt_ft = kwargs["direct_glide_alt_ft"]
    base_to_final_arc_alt = (math.pi * turn_radius_ft) / max(1.0, glide_ratio)
    short_final_alt = SHORT_FINAL_AGL_FT
    required_alt_agl = (direct_glide_alt_ft + LOW_KEY_AGL_FT
                         + base_to_final_arc_alt + short_final_alt) - direct_glide_alt_ft
    # Note: that simplifies to LOW_KEY + arc + final — i.e., the minimum
    # AGL the aircraft needs above the touchdown elevation, ignoring the
    # ground distance (since the direct flight to the field is the actual
    # cost burden, not a "minimum AGL to maneuver" issue). Combine both:
    required_alt_agl = (LOW_KEY_AGL_FT + base_to_final_arc_alt
                         + short_final_alt + direct_glide_alt_ft)
    # required_max_dist: if I had exactly `start_alt_agl_ft` of altitude,
    # what's the farthest direct distance I could glide to make this work?
    # We need start_alt >= (dist/GR) + LOW_KEY + arc + final
    # → dist <= (start_alt - LOW_KEY - arc - final) × GR
    spare = max(0.0, kwargs["start_alt_agl_ft"] - LOW_KEY_AGL_FT
                  - base_to_final_arc_alt - short_final_alt)
    required_max_dist_nm = (spare * glide_ratio) / FT_PER_NM
    kwargs["required_alt_agl_to_make_it_ft"] = required_alt_agl
    kwargs["required_max_dist_nm"] = required_max_dist_nm
    return GlideDiagnostics(**kwargs)
