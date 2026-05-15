"""Terrain elevation lookups via AWS Terrain Tiles (Mapzen Joerd).

Public API:
    elevation_m(lat, lon, zoom=11) -> float
        Bilinearly interpolated terrain elevation in meters MSL.
        Returns NaN if the tile can't be fetched (offline + uncached).

    elevation_batch(latlons, zoom=11) -> np.ndarray
        Vectorized lookup; groups by tile to amortize fetch + decode.

Tile source:
    https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png

Terrarium encoding (per AWS docs):
    elev_m = (R * 256 + G + B / 256) - 32768

Tile math is standard Web Mercator (slippy map convention used by
OpenStreetMap, Mapbox, Leaflet). Tile (z, x, y) covers a square in
projected meters; we go straight to fractional pixel space for
bilinear interp.

Zoom choice:
    z=11 → ~76 m/px at the equator, ~256 px × 256 px tile spans
    ~19 km. CONUS-scale route warms ~150-250 tiles, ~30 MB on disk.

Cache:
    ~/.cache/tallyaero-terrain/{z}/{x}/{y}.png on first fetch.
    In-memory LRU of decoded ndarrays (128 tiles, ~33 MB RAM).
"""
from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Iterable

import numpy as np
import requests
from PIL import Image


# === Configuration ===========================================================

TERRAIN_BASE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium"
TILE_SIZE = 256
DEFAULT_ZOOM = 11
HTTP_TIMEOUT_S = 10.0

# Cache root — overridable via env for tests / packaged builds
_CACHE_ROOT = Path(
    os.environ.get("TALLYAERO_TERRAIN_CACHE")
    or (Path.home() / ".cache" / "tallyaero-terrain")
)


def cache_root() -> Path:
    """Resolved cache directory. Created lazily on first miss."""
    return _CACHE_ROOT


# Shared HTTP session with a connection pool. Reusing the underlying
# TCP/TLS connections cuts cold-cache fetch time ~5x vs naive requests.get
# (which negotiates a new TLS handshake every call).
_SESSION = requests.Session()
_SESSION.mount(
    "https://",
    requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=16),
)


# === Web Mercator tile math ==================================================

def lonlat_to_pixel(lon_deg: float, lat_deg: float, zoom: int) -> tuple[float, float]:
    """Convert lon/lat to global pixel coords at the given zoom.
    Returns (px, py) as floats — fractional pixel preserves sub-tile
    resolution for bilinear interp.
    """
    n = float(1 << zoom)
    px = (lon_deg + 180.0) / 360.0 * n * TILE_SIZE
    # Latitude is clamped to Mercator's valid range to avoid log() blowup.
    lat_clamped = max(-85.05112878, min(85.05112878, lat_deg))
    sin_lat = math.sin(math.radians(lat_clamped))
    py = (0.5 - math.log((1.0 + sin_lat) / (1.0 - sin_lat)) / (4.0 * math.pi)) * n * TILE_SIZE
    return px, py


def pixel_to_tile(px: float, py: float) -> tuple[int, int, float, float]:
    """Split global pixel into (tile_x, tile_y, ix_in_tile, iy_in_tile)."""
    tile_x = int(px // TILE_SIZE)
    tile_y = int(py // TILE_SIZE)
    ix = px - tile_x * TILE_SIZE
    iy = py - tile_y * TILE_SIZE
    return tile_x, tile_y, ix, iy


# === Tile fetch + decode =====================================================

def _tile_path(zoom: int, x: int, y: int) -> Path:
    return cache_root() / str(zoom) / str(x) / f"{y}.png"


def _fetch_tile_bytes(zoom: int, x: int, y: int) -> bytes | None:
    """Fetch a tile from S3, write it to the cache, return bytes.
    Returns None on network failure (offline + uncached → NaN lookup)."""
    url = f"{TERRAIN_BASE_URL}/{zoom}/{x}/{y}.png"
    try:
        resp = _SESSION.get(url, timeout=HTTP_TIMEOUT_S)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    blob = resp.content
    path = _tile_path(zoom, x, y)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
    return blob


def _terrarium_decode(img: Image.Image) -> np.ndarray:
    """Decode a Terrarium-encoded PNG to a float32 grid of elevation
    in meters MSL. Output shape (256, 256)."""
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    return r * 256.0 + g + b / 256.0 - 32768.0


@lru_cache(maxsize=128)
def _load_tile(zoom: int, x: int, y: int) -> np.ndarray | None:
    """Load a decoded tile from disk (or fetch first). Memoized on
    (z, x, y). Returns None if fetch failed and no cache."""
    path = _tile_path(zoom, x, y)
    blob: bytes | None = None
    if path.exists():
        try:
            blob = path.read_bytes()
        except OSError:
            blob = None
    if blob is None:
        blob = _fetch_tile_bytes(zoom, x, y)
    if not blob:
        return None
    try:
        with Image.open(BytesIO(blob)) as img:
            return _terrarium_decode(img)
    except Exception:
        return None


# === Public lookup ===========================================================

def elevation_m(lat_deg: float, lon_deg: float, zoom: int = DEFAULT_ZOOM) -> float:
    """Bilinearly-interpolated terrain elevation in meters MSL.
    NaN if the tile can't be fetched and isn't cached."""
    px, py = lonlat_to_pixel(lon_deg, lat_deg, zoom)
    tile_x, tile_y, ix, iy = pixel_to_tile(px, py)

    grid = _load_tile(zoom, tile_x, tile_y)
    if grid is None:
        return float("nan")

    # Bilinear interpolation across the four neighbors. If the float
    # pixel sits inside the tile we read four pixels from `grid`. If it
    # straddles a tile edge we'd need the neighbor tile; for simplicity
    # we clamp inside this tile and accept ~half-pixel error at edges
    # (sub-meter at our zoom levels).
    ix0 = int(ix)
    iy0 = int(iy)
    ix1 = min(ix0 + 1, TILE_SIZE - 1)
    iy1 = min(iy0 + 1, TILE_SIZE - 1)
    fx = ix - ix0
    fy = iy - iy0

    a = grid[iy0, ix0]
    b = grid[iy0, ix1]
    c = grid[iy1, ix0]
    d = grid[iy1, ix1]
    top = a * (1 - fx) + b * fx
    bot = c * (1 - fx) + d * fx
    return float(top * (1 - fy) + bot * fy)


def elevation_batch(
    latlons: Iterable[tuple[float, float]],
    zoom: int = DEFAULT_ZOOM,
) -> np.ndarray:
    """Vectorized lookup. Returns a float32 array of elevations in m."""
    pts = list(latlons)
    out = np.empty(len(pts), dtype=np.float32)
    for i, (lat, lon) in enumerate(pts):
        out[i] = elevation_m(lat, lon, zoom)
    return out


def feet(m: float) -> float:
    """Helper: meters → feet. Aviation altitudes are in feet, terrain
    tiles are in meters."""
    return m * 3.28084


def clear_memory_cache() -> None:
    """Drop the in-memory decoded-tile LRU. Disk cache untouched."""
    _load_tile.cache_clear()


# === Bbox prefetch ===========================================================

def tiles_in_bbox(
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
    zoom: int = DEFAULT_ZOOM,
) -> list[tuple[int, int]]:
    """Enumerate every (tile_x, tile_y) at `zoom` intersecting the bbox."""
    px_min, py_max = lonlat_to_pixel(lon_min, lat_min, zoom)
    px_max, py_min = lonlat_to_pixel(lon_max, lat_max, zoom)
    tx_min = int(min(px_min, px_max) // TILE_SIZE)
    tx_max = int(max(px_min, px_max) // TILE_SIZE)
    ty_min = int(min(py_min, py_max) // TILE_SIZE)
    ty_max = int(max(py_min, py_max) // TILE_SIZE)
    return [(x, y)
            for x in range(tx_min, tx_max + 1)
            for y in range(ty_min, ty_max + 1)]


def prefetch_bbox(
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
    zoom: int = DEFAULT_ZOOM,
    max_workers: int = 16,
) -> int:
    """Concurrently fetch every tile intersecting the bbox at `zoom`.
    Already-cached tiles are skipped (path.exists() short-circuits).
    Returns the count of tiles touched (cached + newly fetched).
    """
    tiles = tiles_in_bbox(lat_min, lon_min, lat_max, lon_max, zoom)
    return _prefetch_set(set(tiles), zoom, max_workers)


def prefetch_corridor(
    route_samples: list[tuple[float, float]],
    reach_nm: float,
    zoom: int = DEFAULT_ZOOM,
    max_workers: int = 16,
) -> int:
    """Concurrently fetch the minimal DEM tile set needed to ray-march
    glide envelopes of radius `reach_nm` around every route sample.

    A long route's bbox is 90% empty space — fetching every tile is
    wasteful. This walks the actual route and unions the tile set
    around each sample, deduped. For a 600 NM route with 9 NM reach,
    this drops the tile count ~10x vs prefetch_bbox.

    Returns the unique tile count (cached + newly fetched).
    """
    if not route_samples:
        return 0
    needed: set[tuple[int, int]] = set()
    pad_deg = reach_nm / 60.0   # rough NM→deg at mid-lat
    for lat, lon in route_samples:
        sub_tiles = tiles_in_bbox(
            lat - pad_deg, lon - pad_deg,
            lat + pad_deg, lon + pad_deg,
            zoom,
        )
        needed.update(sub_tiles)
    return _prefetch_set(needed, zoom, max_workers)


def _prefetch_set(
    tiles: set[tuple[int, int]] | list[tuple[int, int]],
    zoom: int,
    max_workers: int,
) -> int:
    """Concurrent-fetch helper. Skips tiles already on disk."""
    tile_list = list(tiles)
    missing = [(zoom, x, y) for (x, y) in tile_list
               if not _tile_path(zoom, x, y).exists()]
    if not missing:
        return len(tile_list)

    def _one(args):
        z, x, y = args
        _fetch_tile_bytes(z, x, y)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        list(ex.map(_one, missing))
    return len(tile_list)
