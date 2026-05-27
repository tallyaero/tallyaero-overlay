"""OSM-derived VFR pilotage landmarks — cities, towns, rivers, major
road intersections — to expand the checkpoint candidate pool beyond
airports + VORs.

Reference (FAA-H-8083-25B Ch. 16 §16-2 to §16-3, "Pilotage"):
    "Concentrations of buildings, towns, racetracks, water towers,
    lakes, rivers, bridges, highways, and other distinctive landmarks
    are good aids to dead-reckoning navigation when used in
    combination."

We fetch three categories per route corridor:
  - `populated` — cities + towns with population (typically >= 5k)
  - `rivers`    — named rivers (waterway=river, has `name`)
  - `road_jct`  — intersections of two or more major highways
                  (primary/trunk/motorway)

All three are cached by bbox hash so a recompute on the same route
is instant. First-time fetch can take a few seconds.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Optional

import requests


HTTP_TIMEOUT_S = 30
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)


def _cache_root() -> Path:
    root = Path.home() / ".cache" / "tallyaero-overlay" / "landmarks_osm"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_key(query: str) -> str:
    return hashlib.sha1(query.encode()).hexdigest()[:16]


def _read_cache(key: str) -> Optional[dict]:
    path = _cache_root() / f"{key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(key: str, payload: dict) -> None:
    path = _cache_root() / f"{key}.json"
    try:
        path.write_text(json.dumps(payload))
    except OSError:
        pass


def _fetch_overpass(query: str) -> Optional[dict]:
    cache_key = _cache_key(query)
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            resp = requests.post(
                endpoint, data={"data": query},
                timeout=HTTP_TIMEOUT_S,
                headers={"User-Agent": "tallyaero-overlay/landmarks"},
            )
            if resp.status_code != 200:
                continue
            payload = resp.json()
            _write_cache(cache_key, payload)
            return payload
        except (requests.RequestException, ValueError):
            continue
    return None


def fetch_populated_places(*, lat_min: float, lat_max: float,
                            lon_min: float, lon_max: float,
                            min_population: int = 5000) -> list[dict]:
    """Return list of `{lat, lon, name, ident, kind, population}` for
    populated places ≥ `min_population` inside the bbox.

    `ident` is the city name uppercased + truncated to 6 chars (so it
    fits the checkpoint table column). `kind` is "city".
    """
    query = (
        "[out:json][timeout:25];\n"
        f"node[\"place\"~\"^(city|town)$\"][\"population\"]"
        f"({lat_min},{lon_min},{lat_max},{lon_max});\n"
        "out qt;\n"
    )
    payload = _fetch_overpass(query)
    if not payload:
        return []
    out: list[dict] = []
    for el in payload.get("elements", []):
        if el.get("type") != "node":
            continue
        tags = el.get("tags", {}) or {}
        try:
            pop = int(str(tags.get("population", "0")).replace(",", ""))
        except (TypeError, ValueError):
            pop = 0
        if pop < min_population:
            continue
        name = tags.get("name") or "?"
        out.append({
            "lat": float(el.get("lat", 0.0)),
            "lon": float(el.get("lon", 0.0)),
            "name": name,
            "ident": name[:6].upper(),
            "kind": "city",
            "population": pop,
            "place": tags.get("place"),
        })
    return out


def fetch_river_crossings(*, lat_min: float, lat_max: float,
                           lon_min: float, lon_max: float,
                           leg_a: tuple[float, float],
                           leg_b: tuple[float, float]) -> list[dict]:
    """Find points where the route great-circle (approximated as a
    straight line between leg_a and leg_b in lat/lon) crosses any
    named OSM river. Returns one entry per crossing with `{lat, lon,
    name, ident, kind="river"}`."""
    query = (
        "[out:json][timeout:25];\n"
        f"way[\"waterway\"=\"river\"][\"name\"]"
        f"({lat_min},{lon_min},{lat_max},{lon_max});\n"
        "out geom;\n"
    )
    payload = _fetch_overpass(query)
    if not payload:
        return []

    def _seg_intersect(p1, p2, p3, p4):
        """Returns (lat, lon) of intersection if the two segments cross,
        else None. All points are (lat, lon) tuples; treats as Cartesian
        — fine over ≤ ~100 NM."""
        x1, y1 = p1[1], p1[0]
        x2, y2 = p2[1], p2[0]
        x3, y3 = p3[1], p3[0]
        x4, y4 = p4[1], p4[0]
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-12:
            return None
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom
        if 0 <= t <= 1 and 0 <= u <= 1:
            x = x1 + t * (x2 - x1)
            y = y1 + t * (y2 - y1)
            return (y, x)
        return None

    out: list[dict] = []
    seen_keys: set[str] = set()
    for el in payload.get("elements", []):
        if el.get("type") != "way":
            continue
        tags = el.get("tags", {}) or {}
        name = tags.get("name") or "?"
        geom = el.get("geometry", []) or []
        for i in range(len(geom) - 1):
            p1 = (float(geom[i].get("lat")), float(geom[i].get("lon")))
            p2 = (float(geom[i + 1].get("lat")), float(geom[i + 1].get("lon")))
            hit = _seg_intersect(leg_a, leg_b, p1, p2)
            if hit is None:
                continue
            # Dedup: only one crossing per river per leg.
            key = f"{name}|{round(hit[0], 2)},{round(hit[1], 2)}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append({
                "lat": hit[0], "lon": hit[1],
                "name": name,
                "ident": f"{name[:5].upper()}X",  # X suffix = crossing
                "kind": "river",
            })
    return out


def fetch_road_junctions(*, lat_min: float, lat_max: float,
                          lon_min: float, lon_max: float) -> list[dict]:
    """Major-road intersections inside the bbox. We query for the
    junction nodes that connect at least two of our major-highway
    ways. Falls back to empty on Overpass failure."""
    query = (
        "[out:json][timeout:30];\n"
        f"(\n"
        f"  way[\"highway\"~\"^(motorway|trunk|primary)$\"]"
        f"({lat_min},{lon_min},{lat_max},{lon_max});\n"
        ");\n"
        ">;\n"
        "out body;\n"
    )
    payload = _fetch_overpass(query)
    if not payload:
        return []

    # Count how many qualifying ways each node belongs to.
    way_count: dict[int, int] = {}
    way_names: dict[int, set[str]] = {}
    nodes: dict[int, dict] = {}
    for el in payload.get("elements", []):
        if el.get("type") == "node":
            nodes[el["id"]] = el
        elif el.get("type") == "way":
            nm = (el.get("tags") or {}).get("ref") or (el.get("tags") or {}).get("name")
            for n in el.get("nodes", []) or []:
                way_count[n] = way_count.get(n, 0) + 1
                if nm:
                    way_names.setdefault(n, set()).add(nm)

    out: list[dict] = []
    for node_id, count in way_count.items():
        if count < 2:
            continue
        node = nodes.get(node_id)
        if not node:
            continue
        refs = sorted(way_names.get(node_id, set()))
        if not refs:
            continue
        # Need at least TWO different roads (the junction).
        if len(refs) < 2:
            continue
        # Dedup-ish: prefer numbered refs over names.
        label = "/".join(refs[:2])
        out.append({
            "lat": float(node.get("lat", 0.0)),
            "lon": float(node.get("lon", 0.0)),
            "name": label,
            "ident": label.replace(" ", "")[:8],
            "kind": "road_jct",
        })
    return out
