"""Combined landability mask — slope AND suitable land AND inside
corridor, painted as a single green raster.

The pilot's actual question off-field is "where can I plant this
aircraft?", and that's the intersection of three signals:

  - slope at or below a landable threshold (FAA AFH §18-4: flat)
  - OSM-tagged suitable land (farmland, meadow, grass, etc.)
  - inside the engine-out glide corridor (you can reach it)

Phase 8a painted #1 alone. Phase 8b added #2 as a separate layer.
Phase 8c AND-masks all three so what you see is "where the airplane
can actually land," not "where two of three are true and one is
false." A steep slope inside a wheat field, or a flat patch outside
the corridor, both stop being painted.

Math is plain numpy: rebuild the slope grid (Horn's method,
already in core/terrain_slope.py), rasterize the suitable polygons
via shapely.vectorized at the same grid, AND the two masks, then
AND with the corridor mask the slope module already produces.
"""
from __future__ import annotations

import math
from typing import Callable, Optional

import numpy as np

from core.terrain_slope import (
    sample_elevation_grid, slope_grid_degrees,
    colorize_slope, encode_png_data_url,
)

ElevationFn = Callable[[float, float], float]


def _polygon_mask(
    suitable_geoms,
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
    grid_h: int, grid_w: int,
) -> np.ndarray:
    """Boolean mask of pixels inside any of the suitable-land
    polygons. shapely.vectorized.contains is a single C call over the
    whole grid — orders of magnitude faster than per-pixel Point()."""
    if not suitable_geoms:
        return np.zeros((grid_h, grid_w), dtype=bool)
    try:
        from shapely import vectorized as _shp_vec
        from shapely.ops import unary_union as _shp_union
    except ImportError:
        return np.zeros((grid_h, grid_w), dtype=bool)

    valid_polys = []
    for g in suitable_geoms:
        if g is None or g.is_empty:
            continue
        if not g.is_valid:
            g = g.buffer(0)
        if g.is_valid and not g.is_empty:
            valid_polys.append(g)
    if not valid_polys:
        return np.zeros((grid_h, grid_w), dtype=bool)

    try:
        union = _shp_union(valid_polys)
        if not union.is_valid:
            union = union.buffer(0)
    except Exception:
        return np.zeros((grid_h, grid_w), dtype=bool)

    lats = np.linspace(lat_min, lat_max, grid_h)
    lons = np.linspace(lon_min, lon_max, grid_w)
    lat_grid, lon_grid = np.meshgrid(lats, lons, indexing="ij")
    try:
        inside = _shp_vec.contains(
            union, lon_grid.ravel(), lat_grid.ravel()
        ).reshape((grid_h, grid_w))
    except Exception:
        inside = np.zeros((grid_h, grid_w), dtype=bool)
    return inside


def _corridor_mask(
    corridor_polygon,
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
    grid_h: int, grid_w: int,
) -> np.ndarray:
    if corridor_polygon is None or corridor_polygon.is_empty:
        return np.ones((grid_h, grid_w), dtype=bool)
    try:
        from shapely import vectorized as _shp_vec
        lats = np.linspace(lat_min, lat_max, grid_h)
        lons = np.linspace(lon_min, lon_max, grid_w)
        lat_grid, lon_grid = np.meshgrid(lats, lons, indexing="ij")
        return _shp_vec.contains(
            corridor_polygon, lon_grid.ravel(), lat_grid.ravel()
        ).reshape((grid_h, grid_w))
    except Exception:
        return np.ones((grid_h, grid_w), dtype=bool)


def build_landable_mask_overlay(
    elevation_fn: ElevationFn,
    suitable_geoms: list,
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
    threshold_deg: float = 3.0,
    grid_size: int = 128,
    fill_opacity: float = 0.55,
    corridor_polygon=None,
) -> tuple[str, dict]:
    """End-to-end: sample DEM → slope → suitable mask → corridor mask
    → AND-fold → green PNG.

    Args:
        elevation_fn: lat,lon → elevation meters (NaN ok)
        suitable_geoms: list of shapely Polygons/MultiPolygons (OSM
            suitable-land features). Empty list = mask is all-False
            for the suitable channel, so the overlay is empty.
        threshold_deg: slope threshold for "landable" (FAA AFH §18-4
            operational consensus is 3°).
        corridor_polygon: optional shapely geom; pixels outside it are
            also masked out.

    Returns:
        (data_url, metadata). metadata includes:
            pct_landable_combined: fraction of corridor pixels that
                pass ALL three filters (0-100)
            pct_suitable_alone: pixels passing land-tag check (0-100)
            pct_slope_alone:    pixels passing slope check (0-100)
            n_pixels:           total grid cells
    """
    elev = sample_elevation_grid(
        elevation_fn, lat_min, lon_min, lat_max, lon_max,
        grid_w=grid_size, grid_h=grid_size,
    )
    slope = slope_grid_degrees(elev, lat_min, lon_min, lat_max, lon_max)

    slope_mask = (slope <= threshold_deg) & ~np.isnan(slope)
    suitable_mask = _polygon_mask(
        suitable_geoms,
        lat_min, lon_min, lat_max, lon_max,
        grid_size, grid_size,
    )
    corridor_mask = _corridor_mask(
        corridor_polygon,
        lat_min, lon_min, lat_max, lon_max,
        grid_size, grid_size,
    )

    combined = slope_mask & suitable_mask & corridor_mask

    # Stats are computed against the corridor (the denominator that
    # actually matters to the pilot — "of the places I can reach,
    # what fraction is landable?").
    corridor_cells = int(corridor_mask.sum())
    denom = max(1, corridor_cells)
    pct_combined = 100.0 * float((combined).sum()) / denom
    pct_slope_in_corridor = 100.0 * float((slope_mask & corridor_mask).sum()) / denom
    pct_suit_in_corridor = 100.0 * float((suitable_mask & corridor_mask).sum()) / denom

    # Paint bright lime for landable; lime-300 for inner glow at the
    # border so the patches read against satellite imagery.
    h, w = combined.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[combined] = (132, 204, 22, int(255 * fill_opacity))    # #84cc16 lime-500

    # 1-pixel border: pixels that are landable but have at least one
    # non-landable neighbor get bumped to a brighter lime-300 with
    # full opacity. Outlines every patch, makes the green "pop".
    if combined.any():
        eroded = combined.copy()
        eroded[:-1, :] &= combined[1:, :]
        eroded[1:, :]  &= combined[:-1, :]
        eroded[:, :-1] &= combined[:, 1:]
        eroded[:, 1:]  &= combined[:, :-1]
        border = combined & ~eroded
        rgba[border] = (190, 242, 100, 255)                      # #bef264 lime-300

    # PNG row 0 = top = lat_max — our grid was sampled row 0 = lat_min,
    # so flip vertically to match dl.ImageOverlay's bounds convention.
    rgba = rgba[::-1, :, :]
    data_url = encode_png_data_url(rgba)

    return data_url, {
        "n_pixels": int(grid_size * grid_size),
        "n_corridor_cells": corridor_cells,
        "threshold_deg": threshold_deg,
        "pct_landable_combined": round(pct_combined, 1),
        "pct_slope_alone": round(pct_slope_in_corridor, 1),
        "pct_suitable_alone": round(pct_suit_in_corridor, 1),
    }
