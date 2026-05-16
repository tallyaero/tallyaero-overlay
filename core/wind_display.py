"""Wind visualization helpers — barbs, component math, presentation.

Three pieces of pilot-readable wind UX combine to surface the
per-sample winds-aloft data we already compute:

  1. wind_barb_svg(dir, speed) — meteorological wind barb SVG (stem
     points FROM the wind, feathers/pennants encode speed in 5/10/50
     kt increments) — drawn on the map at picked sample positions.
  2. wind_components(track_deg, wind_dir_deg, wind_speed_kt)
     — headwind/tailwind + crosswind component along a leg, used in
     the per-leg summary row.
  3. pick_barb_indices(n_samples, route_nm) — adaptive density:
     more barbs for short routes (relatively), capped for long ones
     so we don't clutter the map.
"""
from __future__ import annotations

import math


# === Wind barb SVG ==========================================================

def wind_barb_svg(wind_dir_deg: float, wind_speed_kt: float,
                  size_px: int = 36) -> str:
    """Return an SVG string for a wind barb at the given direction and
    speed. The barb's stem points FROM the wind direction
    (meteorological convention). Speed is rounded to nearest 5 kt and
    drawn as combinations of:
      - 50 kt pennant (filled triangle)
      - 10 kt full feather
      -  5 kt half feather

    Below ~2.5 kt: open circle (calm). The full SVG is sized to fit
    `size_px` × `size_px` and rotates the barb in place via CSS
    transform.
    """
    # The SVG-internal coordinate system is 36×36; we let the host
    # render it at `size_px`.
    if wind_speed_kt < 2.5:
        return (
            f'<svg viewBox="0 0 36 36" width="{size_px}" height="{size_px}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<circle cx="18" cy="18" r="4" stroke="#0f172a" '
            f'fill="none" stroke-width="1.6"/></svg>'
        )

    sp = max(5, round(wind_speed_kt / 5.0) * 5)
    n_pennants = sp // 50
    rem = sp % 50
    n_full = rem // 10
    rem = rem % 10
    n_half = rem // 5

    # Stem: line from (18, 32) at base to (18, 4) at tip.
    parts = ['<line x1="18" y1="32" x2="18" y2="4" '
             'stroke="#0f172a" stroke-width="1.8"/>']

    # Feathers/pennants attach near the tip and step inward.
    # Pennants are filled triangles; full feathers are 12 px long;
    # half feathers are 7 px long.
    y_cursor = 4
    for _ in range(n_pennants):
        # Triangle: base at (18, y), point at (6, y+3), tip at (18, y+6)
        parts.append(
            f'<polygon points="18,{y_cursor} 6,{y_cursor + 3} '
            f'18,{y_cursor + 6}" fill="#0f172a"/>'
        )
        y_cursor += 7

    # If we drew pennants leave a tiny gap before feathers
    if n_pennants and (n_full or n_half):
        y_cursor += 1

    for _ in range(n_full):
        # Full feather: angled line from stem to (-12 along the tip side)
        parts.append(
            f'<line x1="18" y1="{y_cursor}" x2="6" y2="{y_cursor + 3}" '
            f'stroke="#0f172a" stroke-width="1.8"/>'
        )
        y_cursor += 4

    for _ in range(n_half):
        # Half feather: shorter, ~7 px
        # Place near the tip, not at the base — at the base of any
        # remaining stem there's no symbol
        parts.append(
            f'<line x1="18" y1="{y_cursor}" x2="11" y2="{y_cursor + 2}" '
            f'stroke="#0f172a" stroke-width="1.8"/>'
        )
        y_cursor += 4

    # Rotate the whole barb so its stem points FROM the wind
    inner = "".join(parts)
    return (
        f'<svg viewBox="0 0 36 36" width="{size_px}" height="{size_px}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'style="transform: rotate({wind_dir_deg}deg); '
        f'transform-origin: 50% 50%;">'
        f'{inner}</svg>'
    )


# === Component math =========================================================

def wind_components(
    track_deg: float, wind_dir_deg: float, wind_speed_kt: float,
) -> tuple[float, float]:
    """Decompose a wind vector relative to a track direction.

    Returns (head_tail_kt, crosswind_kt):
      head_tail > 0 = tailwind, < 0 = headwind
      crosswind > 0 = from the RIGHT side of track (aircraft drifts left),
                 < 0 = from the LEFT side (aircraft drifts right)
    `wind_dir_deg` is the FROM direction (meteorological standard).
    """
    blow_dir = wind_dir_deg + 180.0
    diff = ((blow_dir - track_deg + 540.0) % 360.0) - 180.0
    rad = math.radians(diff)
    head_tail = wind_speed_kt * math.cos(rad)
    crosswind = -wind_speed_kt * math.sin(rad)
    return head_tail, crosswind


def format_wind_components(head_tail: float, crosswind: float) -> str:
    """e.g. 'HW 12 · XW 4R' or 'TW 18 · XW 2L'. Rounds to whole knots.
    Returns empty string for negligible (<1 kt) components."""
    parts = []
    if abs(head_tail) >= 1.0:
        if head_tail < 0:
            parts.append(f"HW {abs(round(head_tail))} kt")
        else:
            parts.append(f"TW {round(head_tail)} kt")
    if abs(crosswind) >= 1.0:
        side = "R" if crosswind > 0 else "L"
        parts.append(f"XW {abs(round(crosswind))}{side}")
    return " · ".join(parts) if parts else "calm"


# === Adaptive sampling ======================================================

def pick_barb_indices(n_samples: int, route_nm: float) -> list[int]:
    """Pick indices into a per-sample list at which to draw wind
    barbs. Returns evenly-spaced indices, count scales with route
    length so short routes still get a few and transcontinental
    routes stay legible.
    """
    if n_samples <= 0:
        return []
    if route_nm < 50:
        n = 3
    elif route_nm < 200:
        n = 5
    elif route_nm < 600:
        n = 8
    else:
        n = 12
    n = min(n, n_samples)
    if n <= 1:
        return [n_samples // 2]
    # Evenly distributed indices including endpoints
    return sorted({round(i * (n_samples - 1) / (n - 1)) for i in range(n)})


# === Route-average wind =====================================================

def route_average_wind(
    winds: list[tuple[float, float]],
) -> tuple[float, float]:
    """Vector-mean of a list of (dir_deg, speed_kt) winds. Returns the
    aggregate (dir_deg, speed_kt). Empty input → (0, 0).
    """
    if not winds:
        return 0.0, 0.0
    u_sum = 0.0
    v_sum = 0.0
    for d, s in winds:
        # FROM direction → blow direction U/V
        rad = math.radians(d)
        u_sum += -math.sin(rad) * s
        v_sum += -math.cos(rad) * s
    u_mean = u_sum / len(winds)
    v_mean = v_sum / len(winds)
    speed = math.sqrt(u_mean * u_mean + v_mean * v_mean)
    if speed < 1e-6:
        return 0.0, 0.0
    dir_deg = math.degrees(math.atan2(-u_mean, -v_mean)) % 360.0
    return dir_deg, speed
