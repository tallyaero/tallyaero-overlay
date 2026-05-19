"""Phase 7f-A — fetch FAA OpenData airspace layers and normalize.

Pulls four ArcGIS FeatureServer layers, paginates 1000 features at
a time, simplifies geometry, and writes lean GeoJSON files into
data/airspace/.

Run once after each NASR 28-day cycle. Output is bundled with the
app so the runtime never hits the network.

Sources (FAA Aeronautical Information Services OpenData portal):
  Class_Airspace                       — B/C/D/E surface polygons
  Special_Use_Airspace                 — MOA/Prohibited/Restricted/Warning/Alert
  National_Defense_Airspace_TFR_Areas  — long-standing security TFRs
                                          (pop-up TFRs come from a different feed)
  Airspace_Schedule                    — active-hours for SUA (joins by NAME)
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
BASE = "https://services6.arcgis.com/ssFJjBXIUyZDrSYZ/arcgis/rest/services"

LAYERS = {
    "class_airspace": f"{BASE}/Class_Airspace/FeatureServer/0",
    "special_use": f"{BASE}/Special_Use_Airspace/FeatureServer/0",
    "tfr": f"{BASE}/National_Defense_Airspace_TFR_Areas/FeatureServer/0",
    "schedule": f"{BASE}/Airspace_Schedule/FeatureServer/0",
}

# Keep file size down. Tolerance is in degrees — ~111 m at the equator.
# 0.0005° ≈ 55 m is fine for polygons that are typically NM-scale.
SIMPLIFY_TOLERANCE_DEG = 0.0005

# Server-side simplification — ArcGIS `maxAllowableOffset` is in
# the source projection's units. Class_Airspace is WGS84 so the
# unit is degrees. ~0.001° ≈ 110 m is plenty for polygons that span
# many NM. Cuts the wire payload from ~100 MB to ~5-15 MB for the
# full Class B/C/D set and is the difference between a successful
# ingest and urllib choking on a malformed gzip stream.
SERVER_TOLERANCE_DEG = 0.001

# Smaller pages keep individual responses sane. Class_Airspace has
# some features with hundreds of vertices each; even at 200 records
# per page the response stays under a few MB.
PAGE_SIZE = 200


def _fetch_page(url: str, offset: int, fmt: str = "geojson") -> dict:
    params = {
        "where": "1=1",
        "outFields": "*",
        "f": fmt,
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
    }
    # Geometry-only knobs — irrelevant (and ignored) on Table layers.
    if fmt == "geojson":
        params["maxAllowableOffset"] = SERVER_TOLERANCE_DEG
        params["geometryPrecision"] = 5
    q = urllib.parse.urlencode(params)
    full = f"{url}/query?{q}"
    req = urllib.request.Request(full, headers={
        "Accept-Encoding": "identity",  # urllib's gzip handling chokes
                                          # on long pages from this server
    })
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _simplify_ring(ring: list, tol: float) -> list:
    """Douglas-Peucker on a single ring. No shapely dep — keep this
    file usable from a fresh venv without the rest of the project."""
    if len(ring) < 4:
        return ring

    def perp_dist(pt, a, b):
        if a == b:
            return ((pt[0] - a[0]) ** 2 + (pt[1] - a[1]) ** 2) ** 0.5
        dx, dy = b[0] - a[0], b[1] - a[1]
        num = abs(dy * pt[0] - dx * pt[1] + b[0] * a[1] - b[1] * a[0])
        den = (dx * dx + dy * dy) ** 0.5
        return num / den

    def rdp(pts, tol):
        if len(pts) < 3:
            return pts
        dmax, idx = 0.0, 0
        for i in range(1, len(pts) - 1):
            d = perp_dist(pts[i], pts[0], pts[-1])
            if d > dmax:
                dmax, idx = d, i
        if dmax > tol:
            left = rdp(pts[: idx + 1], tol)
            right = rdp(pts[idx:], tol)
            return left[:-1] + right
        return [pts[0], pts[-1]]

    return rdp(ring, tol)


def _simplify_geom(geom: dict, tol: float) -> dict:
    if not geom:
        return geom
    t = geom.get("type")
    if t == "Polygon":
        return {"type": t,
                "coordinates": [_simplify_ring(r, tol) for r in geom["coordinates"]]}
    if t == "MultiPolygon":
        return {"type": t,
                "coordinates": [[_simplify_ring(r, tol) for r in poly]
                                 for poly in geom["coordinates"]]}
    return geom


def _slim_properties(layer_key: str, props: dict) -> dict:
    """Keep only the fields we actually use at runtime. ArcGIS feeds
    have ~30 fields per record; we need maybe 6-8.

    Field names below were verified against the live FeatureServer
    metadata on 2026-05-19 — they differ between layers."""
    if layer_key == "class_airspace":
        # CLASS: B/C/D/E, LOWER_VAL/UPPER_VAL in feet (-9998 = SFC, 99999 = unlimited),
        # LOWER_DESC/UPPER_DESC human strings (e.g. "SFC", "10000 MSL")
        keep = ("CLASS", "NAME", "IDENT", "ICAO_ID", "CITY",
                "LOWER_VAL", "UPPER_VAL", "LOWER_DESC", "UPPER_DESC",
                "LOWER_UOM", "UPPER_UOM")
    elif layer_key == "special_use":
        # TYPE_CODE: A (Alert), D (Danger), M (MOA), P (Prohibited),
        # R (Restricted), W (Warning), T (Temporary MOA)
        # Real fields use TIMESOFUSE / CONT_AGENT (not EFF_TIMES / CONTROLLING_AGENCY).
        keep = ("TYPE_CODE", "CLASS", "NAME",
                "LOWER_VAL", "UPPER_VAL",
                "LOWER_DESC", "UPPER_DESC",
                "LOWER_UOM", "UPPER_UOM",
                "TIMESOFUSE", "CONT_AGENT")
    elif layer_key == "tfr":
        # TFR layer is leaner: no altitude fields, has LOCAL_TYPE + WKHR_CODE.
        keep = ("NAME", "TYPE_CODE", "LOCAL_TYPE",
                "WKHR_CODE", "WKHR_RMK",
                "CITY", "STATE", "COUNTRY")
    else:  # schedule
        # Sparse: just APPLIES (the hours-of-use string) keyed by airspace.
        keep = ("FAA_ID", "Airspace_ID", "APPLIES")
    return {k: props.get(k) for k in keep if k in props}


def fetch_layer(key: str, url: str, out: Path) -> int:
    print(f"  {key}: fetching from {url}")
    features: list = []
    offset = 0
    while True:
        page = None
        for attempt in range(4):
            try:
                page = _fetch_page(url, offset)
                break
            except Exception as e:
                wait = 2 ** attempt
                print(f"    page offset={offset} attempt {attempt + 1} failed: {e} — retry in {wait}s")
                time.sleep(wait)
        if page is None:
            raise RuntimeError(
                f"{key}: aborted at offset={offset} after 4 attempts")

        page_feats = page.get("features", [])
        if not page_feats:
            break
        for feat in page_feats:
            props = _slim_properties(key, feat.get("properties") or {})
            geom = _simplify_geom(feat.get("geometry"), SIMPLIFY_TOLERANCE_DEG)
            if not geom:
                continue
            features.append({
                "type": "Feature",
                "properties": props,
                "geometry": geom,
            })
        if len(page_feats) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        print(f"    fetched {len(features)} so far …")

    payload = {"type": "FeatureCollection", "features": features}
    out.write_text(json.dumps(payload, separators=(",", ":")))
    size_kb = out.stat().st_size / 1024.0
    print(f"  {key}: wrote {len(features)} features → {out} ({size_kb:.0f} KB)")
    return len(features)


def fetch_table(key: str, url: str, out: Path) -> int:
    """Airspace_Schedule is a non-spatial Table — fetched as ArcGIS
    JSON attributes and stored as a flat list. Joins to SUA by FAA_ID."""
    print(f"  {key}: fetching from {url} (Table)")
    rows: list = []
    offset = 0
    while True:
        page = None
        for attempt in range(4):
            try:
                page = _fetch_page(url, offset, fmt="json")
                break
            except Exception as e:
                wait = 2 ** attempt
                print(f"    page offset={offset} attempt {attempt + 1} failed: {e} — retry in {wait}s")
                time.sleep(wait)
        if page is None:
            raise RuntimeError(
                f"{key}: aborted at offset={offset} after 4 attempts")
        page_rows = page.get("features", [])
        if not page_rows:
            break
        for r in page_rows:
            attrs = _slim_properties(key, r.get("attributes") or {})
            rows.append(attrs)
        if len(page_rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        print(f"    fetched {len(rows)} so far …")
    out.write_text(json.dumps(rows, separators=(",", ":")))
    size_kb = out.stat().st_size / 1024.0
    print(f"  {key}: wrote {len(rows)} rows → {out} ({size_kb:.0f} KB)")
    return len(rows)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {OUT_DIR}")
    total = 0
    for key, url in LAYERS.items():
        if key == "schedule":
            out = OUT_DIR / "schedule.json"
            total += fetch_table(key, url, out)
        else:
            out = OUT_DIR / f"{key}.geojson"
            total += fetch_layer(key, url, out)
    print(f"\nDone. {total} total records across {len(LAYERS)} layers.")


if __name__ == "__main__":
    sys.exit(main())
