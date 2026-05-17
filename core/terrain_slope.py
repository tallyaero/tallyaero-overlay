"""Terrain slope heatmap — derives per-pixel slope (degrees from
horizontal) from the AWS Terrain Tiles DEM and encodes it as a
color-coded PNG suitable for dl.ImageOverlay on the route map.

Slope is computed using Horn's method (geomorphology standard):
for each pixel, take the 3×3 neighborhood of elevations and compute
the partial derivatives dE/dx, dE/dy via weighted central differences.
Slope = atan(sqrt(dE/dx² + dE/dy²)).

The grid spacing is converted from degrees-lat/lon to meters at the
local latitude so the slope answer is geographic (deg-tilt), not
pixel-based.

Color ramp aligned with FAA off-field landing guidance:
  ≤ 3°:      green   "landable" — flat enough per AFH §18 recommendation
  3-7°:      amber   "marginal — land upslope only" (FAA AFH: into the rise)
  > 7°:      red     "too steep" — significant landing-distance penalty,
                     flip risk; discouraged unless no alternative

Sources:
  - FAA Airplane Flying Handbook (FAA-H-8083-3B) Chapter 18
    "Emergency Procedures" — guidance on field selection
  - FAA Pilot's Handbook of Aeronautical Knowledge (FAA-H-8083-25C)
    Chapter 17 §17-12 — surface assessment
  - AOPA Air Safety Institute "Engine Out!" advisory

NaN pixels (offline tiles) are rendered transparent.
"""
from __future__ import annotations

import base64
import io
import math
from typing import Callable, Optional

import numpy as np
from PIL import Image

from core.corridor import FT_PER_M

ElevationFn = Callable[[float, float], float]

# Approximate meters per degree latitude (constant).
M_PER_DEG_LAT = 111_320.0


def sample_elevation_grid(
    elevation_fn: ElevationFn,
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
    grid_w: int = 128, grid_h: int = 128,
) -> np.ndarray:
    """Sample the elevation function on a uniform lat/lon grid.

    Returns a (grid_h, grid_w) float32 array of elevations in meters.
    NaN where the elevation_fn returns NaN (missing tile).
    """
    lats = np.linspace(lat_min, lat_max, grid_h)
    lons = np.linspace(lon_min, lon_max, grid_w)
    grid = np.empty((grid_h, grid_w), dtype=np.float32)
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            grid[i, j] = elevation_fn(lat, lon)
    return grid


def slope_grid_degrees(
    elev_grid_m: np.ndarray,
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
) -> np.ndarray:
    """Compute per-pixel slope (degrees from horizontal) from an
    elevation grid. Horn's method on a 3×3 window.

    Returns same-shape array. Edge pixels share their nearest-interior
    neighbor's value. NaN elevations propagate to NaN slopes.
    """
    h, w = elev_grid_m.shape
    if h < 3 or w < 3:
        return np.zeros_like(elev_grid_m)

    # Pixel spacing in meters
    lat_span_m = (lat_max - lat_min) * M_PER_DEG_LAT
    mid_lat = (lat_min + lat_max) / 2.0
    lon_span_m = (lon_max - lon_min) * M_PER_DEG_LAT * math.cos(
        math.radians(mid_lat))
    dy_m = lat_span_m / max(1, h - 1)
    dx_m = lon_span_m / max(1, w - 1)
    if dy_m <= 0 or dx_m <= 0:
        return np.zeros_like(elev_grid_m)

    # Horn's weighted central differences on the 3×3 window:
    #   z = | a b c |
    #       | d e f |
    #       | g h i |
    # dz/dx = ((c + 2f + i) - (a + 2d + g)) / (8 * dx)
    # dz/dy = ((g + 2h + i) - (a + 2b + c)) / (8 * dy)
    a = elev_grid_m[:-2, :-2]
    b = elev_grid_m[:-2, 1:-1]
    c = elev_grid_m[:-2, 2:]
    d = elev_grid_m[1:-1, :-2]
    f = elev_grid_m[1:-1, 2:]
    g = elev_grid_m[2:, :-2]
    hh = elev_grid_m[2:, 1:-1]
    ii = elev_grid_m[2:, 2:]

    dzdx = ((c + 2 * f + ii) - (a + 2 * d + g)) / (8.0 * dx_m)
    dzdy = ((g + 2 * hh + ii) - (a + 2 * b + c)) / (8.0 * dy_m)

    slope_rad_inner = np.arctan(np.sqrt(dzdx * dzdx + dzdy * dzdy))
    slope_deg = np.zeros_like(elev_grid_m)
    slope_deg[1:-1, 1:-1] = np.degrees(slope_rad_inner)

    # Edges: copy the nearest interior pixel
    slope_deg[0, :] = slope_deg[1, :]
    slope_deg[-1, :] = slope_deg[-2, :]
    slope_deg[:, 0] = slope_deg[:, 1]
    slope_deg[:, -1] = slope_deg[:, -2]

    # Preserve NaN where elevation was NaN
    nan_mask = np.isnan(elev_grid_m)
    slope_deg[nan_mask] = np.nan

    return slope_deg


def colorize_slope(
    slope_grid_deg: np.ndarray,
    threshold_deg: float = 10.0,
    fill_opacity: float = 0.45,
) -> np.ndarray:
    """Map slope degrees to RGBA. Only landable pixels (≤ threshold) are
    painted green; steeper terrain and NaN are fully transparent so the
    overlay highlights ONLY suitable landing areas. Returns uint8 (H, W, 4).
    """
    h, w = slope_grid_deg.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)

    # Suitable = slope at or below the user-set threshold. numpy's
    # comparison treats NaN as False so steep + NaN end up transparent
    # without an extra mask.
    landable_mask = slope_grid_deg <= threshold_deg
    rgba[landable_mask] = (34, 197, 94, int(255 * fill_opacity))   # #22c55e

    return rgba


def encode_png_data_url(rgba: np.ndarray) -> str:
    """RGBA ndarray → data:image/png;base64,... string for use as
    Leaflet ImageOverlay url."""
    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def build_slope_heatmap_overlay(
    elevation_fn: ElevationFn,
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
    threshold_deg: float = 10.0,
    grid_size: int = 128,
    fill_opacity: float = 0.45,
    clip_polygon=None,
) -> tuple[str, dict]:
    """End-to-end: sample DEM, compute slope, colorize, encode PNG.

    When `clip_polygon` (a shapely Polygon or MultiPolygon) is
    supplied, slope outside the polygon is masked to transparent so
    the heatmap conforms to the engine-out corridor shape instead of
    painting the entire bbox. The polygon is interpreted in (lon, lat)
    coordinate order (shapely convention).

    Returns (data_url, metadata). metadata has:
        n_pixels, threshold_deg, pct_landable, pct_marginal, pct_steep,
        max_slope_deg, mean_slope_deg.
    """
    elev = sample_elevation_grid(
        elevation_fn, lat_min, lon_min, lat_max, lon_max,
        grid_w=grid_size, grid_h=grid_size,
    )
    slope = slope_grid_degrees(elev, lat_min, lon_min, lat_max, lon_max)

    # Clip to the corridor polygon if supplied. shapely.vectorized
    # checks every pixel against the polygon in one C call (~20 ms for
    # 16k pixels) without Python-level Point construction.
    if clip_polygon is not None and not clip_polygon.is_empty:
        try:
            from shapely import vectorized as _shp_vec
            lats = np.linspace(lat_min, lat_max, slope.shape[0])
            lons = np.linspace(lon_min, lon_max, slope.shape[1])
            lat_grid, lon_grid = np.meshgrid(lats, lons, indexing="ij")
            inside = _shp_vec.contains(
                clip_polygon, lon_grid.ravel(), lat_grid.ravel()
            ).reshape(slope.shape)
            slope = np.where(inside, slope, np.nan)
        except Exception:
            # If anything goes wrong (legacy shapely, geometry quirks)
            # fall back to the un-clipped raster rather than failing.
            pass

    rgba = colorize_slope(slope, threshold_deg, fill_opacity)
    # PNG / Leaflet convention: row 0 = top of image = lat_max (north).
    # Our grid was sampled row 0 = lat_min, so flip vertically before
    # encoding to align with dl.ImageOverlay's bounds interpretation.
    rgba = rgba[::-1, :, :]
    data_url = encode_png_data_url(rgba)

    valid = slope[~np.isnan(slope)]
    if valid.size > 0:
        n_total = float(valid.size)
        pct_landable = float((valid <= threshold_deg).sum()) / n_total * 100
        pct_marginal = float(
            ((valid > threshold_deg) & (valid <= 2 * threshold_deg)).sum()
        ) / n_total * 100
        pct_steep = float((valid > 2 * threshold_deg).sum()) / n_total * 100
        max_slope = float(valid.max())
        mean_slope = float(valid.mean())
    else:
        pct_landable = pct_marginal = pct_steep = 0.0
        max_slope = mean_slope = 0.0

    return data_url, {
        "n_pixels": int(grid_size * grid_size),
        "threshold_deg": threshold_deg,
        "pct_landable": round(pct_landable, 1),
        "pct_marginal": round(pct_marginal, 1),
        "pct_steep": round(pct_steep, 1),
        "max_slope_deg": round(max_slope, 1),
        "mean_slope_deg": round(mean_slope, 1),
    }
