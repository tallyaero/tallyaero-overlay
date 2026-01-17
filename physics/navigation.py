"""
Geographic and navigation calculations.
Single canonical versions of all navigation functions (deduped from utility.py).
"""
import math
from geopy.point import Point as GeoPoint
from geopy.distance import distance


def point_from(p, bearing_deg: float, dist_nm: float):
    """
    Calculate destination point from starting point, bearing, and distance.

    Args:
        p: Starting point (geopy Point)
        bearing_deg: Bearing in degrees (0=N, 90=E)
        dist_nm: Distance in nautical miles

    Returns:
        Destination point (geopy Point)
    """
    return distance(nautical=dist_nm).destination(p, bearing_deg)


def calculate_initial_compass_bearing(pointA, pointB) -> float:
    """
    Calculate initial compass bearing between two points.

    Args:
        pointA: Starting point (geopy Point)
        pointB: Ending point (geopy Point)

    Returns:
        Initial bearing in degrees (0-360)
    """
    lat1 = math.radians(pointA.latitude)
    lat2 = math.radians(pointB.latitude)
    diff_long = math.radians(pointB.longitude - pointA.longitude)
    x = math.sin(diff_long) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(diff_long))
    initial_bearing = math.atan2(x, y)
    return (math.degrees(initial_bearing) + 360) % 360


def wind_components(wind_dir_deg: float, wind_speed_kt: float) -> tuple:
    """
    Convert wind direction and speed to north/east components.

    Args:
        wind_dir_deg: Wind direction (FROM) in degrees
        wind_speed_kt: Wind speed in knots

    Returns:
        Tuple of (north_component, east_component) in knots
    """
    wind_rad = math.radians(wind_dir_deg)
    return wind_speed_kt * math.cos(wind_rad), wind_speed_kt * math.sin(wind_rad)


def estimate_energy_bleed_distance(start_ias_kias: float, best_glide_kias: float,
                                    tau: float, tas_fps: float) -> float:
    """
    Estimate the distance required to bleed speed from start IAS to best glide IAS.

    Args:
        start_ias_kias: Starting indicated airspeed in KIAS
        best_glide_kias: Best glide IAS in KIAS
        tau: Time constant for speed decay
        tas_fps: True airspeed in feet per second

    Returns:
        Distance in meters
    """
    if start_ias_kias <= best_glide_kias + 1:
        return 0.0

    # Target IAS is slightly above best glide to ensure decay stability
    decay_target_ias = max(best_glide_kias + 5, best_glide_kias + 0.05 * (start_ias_kias - best_glide_kias))
    decay_fraction = 1 - ((decay_target_ias - best_glide_kias) / (start_ias_kias - best_glide_kias))
    decay_fraction = max(decay_fraction, 1e-6)

    t_seconds = -tau * math.log(decay_fraction)
    distance_m = tas_fps * t_seconds

    return round(distance_m, 1)


# --- Internal helper functions ---

def _wrap_360(deg: float) -> float:
    """Normalize angle to 0-360 range."""
    deg = float(deg) % 360.0
    return deg + 360.0 if deg < 0 else deg


def _angle_diff_deg(a: float, b: float) -> float:
    """Calculate signed shortest angle difference (a-b) in degrees, range [-180, 180]."""
    d = (float(a) - float(b) + 180.0) % 360.0 - 180.0
    return d


def _bearing_to_unit_ne(bearing_deg: float) -> tuple:
    """
    Convert bearing to north/east unit vector.

    Args:
        bearing_deg: Bearing in degrees (0=N, 90=E)

    Returns:
        Tuple of (north, east) unit components
    """
    br = math.radians(_wrap_360(bearing_deg))
    return (math.cos(br), math.sin(br))


def _cross_track_distance_ft(point_a, line_origin, line_bearing_deg: float) -> float:
    """
    Calculate signed cross track distance from point to infinite line.

    Args:
        point_a: The point to measure from
        line_origin: Origin point of the line
        line_bearing_deg: Bearing of the line

    Returns:
        Signed cross track distance in feet (positive = right of line)
    """
    dist_ft = distance(line_origin, point_a).feet
    brg = calculate_initial_compass_bearing(line_origin, point_a)
    dn, de = _bearing_to_unit_ne(brg)
    p_n = dist_ft * dn
    p_e = dist_ft * de

    ln, le = _bearing_to_unit_ne(line_bearing_deg)
    xtrack = (ln * p_e) - (le * p_n)
    return xtrack


def _heading_from_track_components(vn_fps: float, ve_fps: float) -> float:
    """
    Calculate heading from velocity components.

    Args:
        vn_fps: North velocity component in fps
        ve_fps: East velocity component in fps

    Returns:
        Heading in degrees (0=N, 90=E)
    """
    if abs(vn_fps) < 1e-9 and abs(ve_fps) < 1e-9:
        return 0.0
    return _wrap_360(math.degrees(math.atan2(ve_fps, vn_fps)))


def _wind_components_from_dir(wind_from_deg: float, wind_speed_kt: float) -> tuple:
    """
    Convert wind direction to velocity components (wind TO direction).

    Args:
        wind_from_deg: Wind direction (FROM) in degrees
        wind_speed_kt: Wind speed in knots

    Returns:
        Tuple of (north_fps, east_fps) velocity components
    """
    wind_to_deg = _wrap_360(wind_from_deg + 180.0)
    w_fps = float(wind_speed_kt) * 1.68781
    w_to = math.radians(wind_to_deg)
    wn = w_fps * math.cos(w_to)
    we = w_fps * math.sin(w_to)
    return wn, we


def _local_xy_ft(origin_pt, pt) -> tuple:
    """
    Convert lat/lon to local tangent plane coordinates (equirectangular projection).

    Args:
        origin_pt: Origin point with latitude/longitude attributes
        pt: Target point with latitude/longitude attributes

    Returns:
        Tuple of (x_east_ft, y_north_ft)
    """
    lat0 = math.radians(origin_pt.latitude)
    dlat = math.radians(pt.latitude - origin_pt.latitude)
    dlon = math.radians(pt.longitude - origin_pt.longitude)
    R_earth = 6371000.0  # meters

    y_m = dlat * R_earth
    x_m = dlon * R_earth * math.cos(lat0)

    ft_per_m = 3.28084
    return x_m * ft_per_m, y_m * ft_per_m


def _cross_track_to_centerline_ft(start_pt, cur_pt, runway_heading_deg: float) -> tuple:
    """
    Calculate cross track and along track distance relative to runway centerline.

    Args:
        start_pt: Runway threshold point
        cur_pt: Current position
        runway_heading_deg: Runway heading

    Returns:
        Tuple of (cross_track_ft, along_track_ft)
    """
    x, y = _local_xy_ft(start_pt, cur_pt)

    theta = math.radians(_wrap_360(runway_heading_deg))
    ux = math.sin(theta)  # east component
    uy = math.cos(theta)  # north component

    along = x * ux + y * uy
    cross = x * uy - y * ux
    return cross, along
