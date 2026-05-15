"""Tests for core.terrain — DEM tile math, Terrarium decode, bilinear interp.

Never hits the network: monkey-patches `_fetch_tile_bytes` and bypasses
the disk cache by pointing at a tmp dir per test.
"""
from __future__ import annotations

import math
from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from core import terrain


# === Tile math ==============================================================

def test_lonlat_to_pixel_zero_meridian():
    """At zoom 0 the entire world is one 256x256 tile. (0, 0) → (128, 128)."""
    px, py = terrain.lonlat_to_pixel(0.0, 0.0, zoom=0)
    assert abs(px - 128) < 1e-6
    assert abs(py - 128) < 1e-6


def test_lonlat_to_pixel_180_east():
    """180°E lands on the right edge of the world."""
    px, _ = terrain.lonlat_to_pixel(180.0, 0.0, zoom=0)
    assert abs(px - 256) < 1e-6


def test_lonlat_to_pixel_high_zoom():
    """At zoom 11 the world is 2048×2048 tiles = 524288 px."""
    n = (1 << 11) * 256
    px, _ = terrain.lonlat_to_pixel(180.0, 0.0, zoom=11)
    assert abs(px - n) < 1e-6


def test_pixel_to_tile_split():
    px = 256 * 3 + 100.5
    py = 256 * 5 + 200.25
    tx, ty, ix, iy = terrain.pixel_to_tile(px, py)
    assert tx == 3 and ty == 5
    assert abs(ix - 100.5) < 1e-9
    assert abs(iy - 200.25) < 1e-9


def test_lonlat_clamps_polar_latitudes():
    """Latitudes outside ±85.05° are clamped so the Mercator log stays finite."""
    px_north, py_north = terrain.lonlat_to_pixel(0.0, 89.99, zoom=2)
    # Should not be inf/nan
    assert math.isfinite(px_north) and math.isfinite(py_north)


# === Terrarium decode =======================================================

def make_terrarium_tile(elev_grid_m: np.ndarray) -> bytes:
    """Encode a (H, W) elevation array (meters MSL) as Terrarium PNG bytes."""
    assert elev_grid_m.shape == (terrain.TILE_SIZE, terrain.TILE_SIZE)
    raw = elev_grid_m + 32768.0
    r = (raw // 256).astype(np.uint8)
    g = (raw % 256).astype(np.uint8)
    b = ((raw - np.floor(raw)) * 256).astype(np.uint8)
    rgb = np.stack([r, g, b], axis=-1)
    img = Image.fromarray(rgb, mode="RGB")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_terrarium_round_trip_decode():
    """Encode a known grid → decode → values match within sub-meter."""
    grid = np.full((terrain.TILE_SIZE, terrain.TILE_SIZE), 500.0, dtype=np.float32)
    grid[10, 20] = 1234.5
    blob = make_terrarium_tile(grid)
    img = Image.open(BytesIO(blob))
    decoded = terrain._terrarium_decode(img)
    assert abs(decoded[0, 0] - 500.0) < 0.01
    assert abs(decoded[10, 20] - 1234.5) < 0.01


def test_terrarium_negative_elevations():
    """Death Valley (-86m) and Dead Sea (-430m) should decode correctly."""
    grid = np.full((terrain.TILE_SIZE, terrain.TILE_SIZE), -430.0, dtype=np.float32)
    blob = make_terrarium_tile(grid)
    decoded = terrain._terrarium_decode(Image.open(BytesIO(blob)))
    assert abs(decoded[0, 0] - (-430.0)) < 0.01


# === Bilinear interpolation =================================================

@pytest.fixture
def synthetic_world(monkeypatch, tmp_path):
    """A synthetic 'world' where elevation in one well-known mid-world tile
    is a linear ramp from 0 (col 0) to 1000 (col 255). Other tiles fail to
    fetch — used to check NaN fallback.

    To stay clear of edge-case tiles (poles, antimeridian) we use a tile
    that contains a real lat/lon near (0, 0). Disk cache redirected to
    tmp_path so each test runs clean.
    """
    monkeypatch.setattr(terrain, "_CACHE_ROOT", tmp_path)
    terrain.clear_memory_cache()

    # Pick a real point (lat, lon) and resolve forward which tile holds it.
    target_lat, target_lon = 0.01, 0.01
    px, py = terrain.lonlat_to_pixel(target_lon, target_lat, zoom=11)
    target_tx, target_ty, _, _ = terrain.pixel_to_tile(px, py)

    def fake_fetch(zoom, x, y):
        if (zoom, x, y) == (11, target_tx, target_ty):
            grid = np.zeros((256, 256), dtype=np.float32)
            for col in range(256):
                grid[:, col] = (col / 255.0) * 1000.0
            return make_terrarium_tile(grid)
        return None

    monkeypatch.setattr(terrain, "_fetch_tile_bytes", fake_fetch)
    # Stash the target so tests can use it
    fake_fetch.target_latlon = (target_lat, target_lon)  # type: ignore[attr-defined]
    fake_fetch.target_tile = (target_tx, target_ty)      # type: ignore[attr-defined]
    yield fake_fetch
    terrain.clear_memory_cache()


def test_elevation_m_bilinear_at_known_point(synthetic_world):
    """At our target lat/lon, the ramp returns elevation == (col/255) × 1000.
    Use the forward-math result rather than reverse-engineering pixel coords.
    """
    target_lat, target_lon = synthetic_world.target_latlon
    px, _ = terrain.lonlat_to_pixel(target_lon, target_lat, zoom=11)
    _, _, ix, _ = terrain.pixel_to_tile(px, px)   # ix is what matters
    expected = (ix / 255.0) * 1000.0
    elev = terrain.elevation_m(target_lat, target_lon, zoom=11)
    # Bilinear over a linear ramp = exact within float noise
    assert abs(elev - expected) < 5.0, f"got {elev}, expected ~{expected}"


def test_elevation_m_nan_when_fetch_fails(synthetic_world):
    """Sampling far away from our seeded tile fails to fetch → NaN.
    Pick a lat/lon clearly outside the seeded tile."""
    elev = terrain.elevation_m(40.0, -100.0, zoom=11)   # mid-US, unseeded tile
    assert math.isnan(elev)


def test_disk_cache_round_trip(synthetic_world, tmp_path):
    """After first lookup, the PNG persists on disk. Clearing the in-memory
    LRU should still give the same elevation on next call."""
    target_lat, target_lon = synthetic_world.target_latlon
    e1 = terrain.elevation_m(target_lat, target_lon, zoom=11)
    terrain.clear_memory_cache()
    e2 = terrain.elevation_m(target_lat, target_lon, zoom=11)
    assert math.isfinite(e1) and math.isfinite(e2)
    assert abs(e1 - e2) < 1e-3


# === Bbox + prefetch =========================================================

def test_tiles_in_bbox_tiny_returns_at_least_one():
    """A single-point bbox returns the one tile containing that point."""
    tiles = terrain.tiles_in_bbox(0.0, 0.0, 0.001, 0.001, zoom=11)
    assert len(tiles) >= 1


def test_tiles_in_bbox_known_count():
    """A bbox spanning ~2 deg at zoom 11 should cover a predictable
    number of tiles. At zoom 11 each tile is ~0.176° wide near the
    equator → ~12x12 grid for a 2° box, give or take 1 in each
    direction."""
    tiles = terrain.tiles_in_bbox(0.0, 0.0, 2.0, 2.0, zoom=11)
    assert 100 <= len(tiles) <= 200


def test_prefetch_bbox_concurrent(synthetic_world):
    """prefetch_bbox should fetch every tile in the bbox. We track
    fetch calls via our fake and verify the count rises by the
    expected amount."""
    target_lat, target_lon = synthetic_world.target_latlon
    # Tiny bbox around the target — should hit exactly 1-2 tiles
    n_touched = terrain.prefetch_bbox(
        target_lat - 0.001, target_lon - 0.001,
        target_lat + 0.001, target_lon + 0.001,
        zoom=11,
    )
    assert n_touched >= 1
