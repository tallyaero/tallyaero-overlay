"""Tests for core.terrain_slope — slope math, color mapping, end-to-end."""
from __future__ import annotations

import math
import numpy as np
import pytest

from core.terrain_slope import (
    sample_elevation_grid, slope_grid_degrees, colorize_slope,
    encode_png_data_url, build_slope_heatmap_overlay,
)


# === Slope math =============================================================

def test_slope_flat_terrain_is_zero():
    """Uniform elevation grid → 0° slope everywhere."""
    grid = np.full((20, 20), 100.0, dtype=np.float32)
    slopes = slope_grid_degrees(grid, 33.0, -80.0, 33.5, -79.5)
    assert np.allclose(slopes, 0.0, atol=0.01)


def test_slope_uniform_ramp():
    """A linear elevation ramp gives a constant slope."""
    h, w = 20, 20
    # 100 m rise over the 0.5° lat span (~55.6 km)
    # slope = atan(100 / 55_660) ≈ 0.103°
    grid = np.tile(np.linspace(0, 100, h).reshape(-1, 1), (1, w))
    slopes = slope_grid_degrees(grid, 33.0, -80.0, 33.5, -79.5)
    # Interior pixels should all be ~0.1°
    interior = slopes[1:-1, 1:-1]
    assert 0.05 < interior.mean() < 0.2


def test_slope_steep_cliff():
    """A 1000 m cliff at column 10 → very steep slope there."""
    h, w = 20, 20
    grid = np.zeros((h, w), dtype=np.float32)
    grid[:, 10:] = 1000.0   # 1000 m wall starting at col 10
    slopes = slope_grid_degrees(grid, 33.0, -80.0, 33.01, -79.99)
    # The cliff edge should be very steep (>30°)
    assert slopes[10, 10] > 30 or slopes[10, 9] > 30


def test_slope_preserves_nan():
    """NaN elevations → NaN slopes."""
    grid = np.full((10, 10), 100.0, dtype=np.float32)
    grid[5, 5] = np.nan
    slopes = slope_grid_degrees(grid, 33.0, -80.0, 33.1, -79.9)
    assert np.isnan(slopes[5, 5])


def test_slope_small_grid_returns_zeros():
    grid = np.array([[100.0]], dtype=np.float32)
    slopes = slope_grid_degrees(grid, 33.0, -80.0, 33.01, -79.99)
    assert slopes.shape == (1, 1) and slopes[0, 0] == 0


# === Color mapping ==========================================================

def test_colorize_flat_is_green():
    """Slope 1° with threshold 3° → green pixel."""
    slopes = np.array([[1.0]])
    rgba = colorize_slope(slopes, threshold_deg=3.0)
    # Green tailwind palette is (34, 197, 94)
    assert rgba[0, 0, 0] == 34
    assert rgba[0, 0, 1] == 197
    assert rgba[0, 0, 2] == 94


def test_colorize_marginal_is_transparent():
    """Slope above threshold → fully transparent (only suitable areas
    are painted under the Phase 8b "show only suitable" rule)."""
    slopes = np.array([[5.0]])
    rgba = colorize_slope(slopes, threshold_deg=3.0)
    assert rgba[0, 0, 3] == 0   # alpha = 0


def test_colorize_steep_is_transparent():
    """Steep slope → transparent under the suitable-only rule."""
    slopes = np.array([[20.0]])
    rgba = colorize_slope(slopes, threshold_deg=3.0)
    assert rgba[0, 0, 3] == 0


def test_colorize_nan_is_transparent():
    slopes = np.array([[float("nan")]])
    rgba = colorize_slope(slopes, threshold_deg=3.0)
    assert rgba[0, 0, 3] == 0   # alpha = 0


def test_colorize_at_threshold_is_green():
    """Boundary case: slope exactly == threshold should be painted."""
    slopes = np.array([[3.0]])
    rgba = colorize_slope(slopes, threshold_deg=3.0)
    assert rgba[0, 0, 0] == 34 and rgba[0, 0, 3] > 0


# === Data URL encoding ======================================================

def test_data_url_format():
    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    rgba[..., 0] = 100  # red channel
    url = encode_png_data_url(rgba)
    assert url.startswith("data:image/png;base64,")
    assert len(url) > 50   # non-trivial PNG payload


# === End-to-end =============================================================

def test_build_heatmap_constant_elev_all_landable():
    """Constant 100m elevation → 0° everywhere → 100% landable."""
    elev_fn = lambda lat, lon: 100.0
    url, meta = build_slope_heatmap_overlay(
        elev_fn, 33.0, -80.0, 33.5, -79.5,
        threshold_deg=3.0, grid_size=32,
    )
    assert url.startswith("data:image/png;base64,")
    assert meta["pct_landable"] > 95
    assert meta["pct_steep"] == 0
    assert meta["max_slope_deg"] < 1


def test_build_heatmap_synthetic_mountain():
    """A peaked elevation function should produce non-zero steep area."""
    def elev_fn(lat, lon):
        # Gaussian peak at center
        cx, cy = 33.25, -79.75
        d2 = (lat - cx) ** 2 + (lon - cy) ** 2
        return 3000.0 * math.exp(-d2 / 0.005)
    url, meta = build_slope_heatmap_overlay(
        elev_fn, 33.0, -80.0, 33.5, -79.5,
        threshold_deg=3.0, grid_size=32,
    )
    assert meta["pct_steep"] > 5   # at least some pixels are steep
    assert meta["max_slope_deg"] > 5


def test_build_heatmap_meta_shape():
    """Metadata dict has all expected keys."""
    elev_fn = lambda lat, lon: 50.0
    _, meta = build_slope_heatmap_overlay(
        elev_fn, 33.0, -80.0, 33.1, -79.9,
        threshold_deg=3.0, grid_size=16,
    )
    for key in ("n_pixels", "threshold_deg", "pct_landable",
                "pct_marginal", "pct_steep", "max_slope_deg",
                "mean_slope_deg"):
        assert key in meta
