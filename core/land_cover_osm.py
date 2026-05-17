"""Suitable-land polygons via OSM Overpass API — what a pilot would
actually try to land in if the engine quits.

Per FAA AFH §18-4 ("Emergency Landing"), the ideal off-field landing
target is a flat, open area free of obstacles. We map that to a small
set of OpenStreetMap tags that real ground truth shows correlate well
with "open, level, soft-vegetation surface":

    landuse=farmland     plowed/planted fields, very large open areas
    landuse=meadow       grass meadows, open
    landuse=grass        landscaped grass, parks/golf
    landuse=pasture      grazing land, generally smooth
    natural=grassland    natural grass plains
    natural=heath        low-vegetation heathland

This is the inverse of the original hazard-tagging design: we no
longer paint water/forest/urban red, we paint farmland/meadow/etc.
green so the pilot sees "land here" rather than "avoid here." Slope
suitability is layered on top (Phase 8a) using the same green-only
treatment.

Cache: responses are saved per bbox-hash in
`~/.cache/tallyaero-landcover/{hash}.json` with a 7-day TTL.

Network: tries `overpass-api.de` first with `overpass.kumi.systems`
as fallback. 30 s timeout per attempt. Returns an empty
FeatureCollection on total failure so callers render gracefully.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

import requests

OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
HTTP_TIMEOUT_S = 30.0
CACHE_TTL_S = 7 * 24 * 3600   # 7 days

_CACHE_ROOT = Path(
    os.environ.get("TALLYAERO_LANDCOVER_CACHE")
    or (Path.home() / ".cache" / "tallyaero-landcover")
)


def cache_root() -> Path:
    return _CACHE_ROOT


# === Overpass query =========================================================

_OVERPASS_QUERY_TEMPLATE = """
[out:json][timeout:25];
(
  way["landuse"="farmland"]({s},{w},{n},{e});
  relation["landuse"="farmland"]({s},{w},{n},{e});
  way["landuse"="meadow"]({s},{w},{n},{e});
  relation["landuse"="meadow"]({s},{w},{n},{e});
  way["landuse"="grass"]({s},{w},{n},{e});
  relation["landuse"="grass"]({s},{w},{n},{e});
  way["landuse"="pasture"]({s},{w},{n},{e});
  relation["landuse"="pasture"]({s},{w},{n},{e});
  way["natural"="grassland"]({s},{w},{n},{e});
  relation["natural"="grassland"]({s},{w},{n},{e});
  way["natural"="heath"]({s},{w},{n},{e});
  relation["natural"="heath"]({s},{w},{n},{e});
  way["natural"="water"]({s},{w},{n},{e});
  relation["natural"="water"]({s},{w},{n},{e});
  way["waterway"="riverbank"]({s},{w},{n},{e});
);
out geom;
"""


def _bbox_cache_key(s: float, w: float, n: float, e: float) -> str:
    """Round bbox to 0.05° grid so nearby compute-calls share cache."""
    q = "_".join(f"{round(v * 20) / 20:.3f}" for v in (s, w, n, e))
    return hashlib.sha1(q.encode()).hexdigest()[:16]


def _read_cache(key: str) -> Optional[dict]:
    path = _CACHE_ROOT / f"{key}.json"
    if not path.exists():
        return None
    try:
        if time.time() - path.stat().st_mtime > CACHE_TTL_S:
            return None
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(key: str, payload: dict) -> None:
    path = _CACHE_ROOT / f"{key}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    except OSError:
        pass


def _fetch_overpass(query: str) -> Optional[dict]:
    """Try each Overpass endpoint until one succeeds; None on total fail."""
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            resp = requests.post(
                endpoint, data={"data": query},
                timeout=HTTP_TIMEOUT_S,
                headers={"User-Agent": "tallyaero-overlay/8b"},
            )
            if resp.status_code != 200:
                continue
            return resp.json()
        except (requests.RequestException, ValueError):
            continue
    return None


# === Feature classification =================================================

_SUITABLE_LANDUSE = {"farmland", "meadow", "grass", "pasture"}
_SUITABLE_NATURAL = {"grassland", "heath"}


def classify_feature(tags: dict) -> Optional[str]:
    """Return one of:
      - 'suitable' — open, level surface a pilot would aim for (FAA
        AFH §18-4 "flat, firm, open" target list)
      - 'water'    — ditching option per AFH §18-7. NOT the same as
        suitable land; surfaced separately so the pilot sees the
        option without it being mistaken for a wheat field.
      - None       — everything else.
    """
    if not tags:
        return None
    if tags.get("landuse", "") in _SUITABLE_LANDUSE:
        return "suitable"
    if tags.get("natural", "") in _SUITABLE_NATURAL:
        return "suitable"
    if tags.get("natural", "") == "water":
        return "water"
    if tags.get("waterway", "") == "riverbank":
        return "water"
    return None


def _element_to_geojson_geom(elem: dict) -> Optional[dict]:
    """Convert an Overpass `way` or `relation` element with geom into a
    GeoJSON-style polygon ready for dl.GeoJSON."""
    kind = elem.get("type")
    if kind == "way":
        geom = elem.get("geometry") or []
        if len(geom) < 4:
            return None
        # GeoJSON coordinates are [lon, lat]
        coords = [[g["lon"], g["lat"]] for g in geom]
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        return {"type": "Polygon", "coordinates": [coords]}
    if kind == "relation":
        polygons = []
        for m in (elem.get("members") or []):
            if m.get("role") != "outer":
                continue
            geom = m.get("geometry") or []
            if len(geom) < 4:
                continue
            coords = [[g["lon"], g["lat"]] for g in geom]
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            polygons.append([coords])
        if not polygons:
            return None
        if len(polygons) == 1:
            return {"type": "Polygon", "coordinates": polygons[0]}
        return {"type": "MultiPolygon", "coordinates": polygons}
    return None


# === Public entry point =====================================================

def fetch_landing_options(
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
) -> dict:
    """Return categorized GeoJSON FeatureCollections:

        {
          "suitable": FeatureCollection of farmland/meadow/etc.,
          "water":    FeatureCollection of lakes/rivers/etc.,
        }

    Both buckets together are the visual options a pilot has if the
    engine fails. Suitable = AFH §18-4 ideal target. Water = AFH
    §18-7 ditching option (NOT equivalent to suitable land).

    Returns both empty FeatureCollections on total fetch failure.
    """
    key = _bbox_cache_key(lat_min, lon_min, lat_max, lon_max)
    cached = _read_cache(key)
    if (cached is not None
            and isinstance(cached, dict)
            and "suitable" in cached
            and "water" in cached):
        return cached
    # Old single-FC cache shape — ignore and refetch into new shape.

    query = _OVERPASS_QUERY_TEMPLATE.format(
        s=lat_min, w=lon_min, n=lat_max, e=lon_max,
    )
    payload = _fetch_overpass(query)

    buckets: dict[str, list[dict]] = {"suitable": [], "water": []}
    if payload and isinstance(payload.get("elements"), list):
        for elem in payload["elements"]:
            tags = elem.get("tags") or {}
            cat = classify_feature(tags)
            if cat is None:
                continue
            geom = _element_to_geojson_geom(elem)
            if geom is None:
                continue
            buckets[cat].append({
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "name": tags.get("name", ""),
                    "category": cat,
                    "landuse": tags.get("landuse", ""),
                    "natural": tags.get("natural", ""),
                    "waterway": tags.get("waterway", ""),
                },
            })

    result = {
        cat: {"type": "FeatureCollection", "features": feats}
        for cat, feats in buckets.items()
    }
    _write_cache(key, result)
    return result


# Back-compat: old name returns just the suitable bucket.
def fetch_suitable_land(
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
) -> dict:
    return fetch_landing_options(
        lat_min, lon_min, lat_max, lon_max)["suitable"]


def fetch_land_cover(
    lat_min: float, lon_min: float,
    lat_max: float, lon_max: float,
) -> dict:
    return fetch_landing_options(lat_min, lon_min, lat_max, lon_max)


# === Suitable-area styling ==================================================

# Same green as the slope-landable layer so the two suitability signals
# read as one composite "landable" wash. Slightly lower opacity so the
# slope green can stack visually when both are on.
SUITABLE_LAND_STYLE = {
    "color": "#15803d", "weight": 1,
    "fillColor": "#22c55e", "fillOpacity": 0.22,
}

# Water = AFH §18-7 ditching option. Blue, NOT red — AFH explicitly
# states water is not worst-case. Distinct from the green suitable
# wash so the pilot reads them as two separate decisions.
WATER_STYLE = {
    "color": "#1e3a8a", "weight": 1,
    "fillColor": "#3b82f6", "fillOpacity": 0.30,
}

# Back-compat for code that still imports LAND_COVER_STYLES.
LAND_COVER_STYLES = {
    "suitable": SUITABLE_LAND_STYLE,
    "water": WATER_STYLE,
}
