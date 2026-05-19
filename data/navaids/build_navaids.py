"""Phase 7N-b/c — fetch FAA OpenData NAVAIDs + designated fixes.

Pulls two ArcGIS FeatureServer layers and writes lean JSON files:

  NavaidComponents (~2200 records) — VOR / DME / VORTAC / NDB / TACAN
                                     with IDENT, NAME, FREQUENCY, lat/lon,
                                     ELEVATION, TYPE_CODE, MAGVAR.
  DesignatedPoints (~17000 records) — Named 5-letter intersections / fixes
                                       with IDENT, lat/lon, TYPE_CODE.

The runtime never hits the network — output is bundled with the
app. Re-run after each NASR 28-day cycle.
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
    "navaids": f"{BASE}/NavaidComponents/FeatureServer/0",
    "fixes": f"{BASE}/DesignatedPoints/FeatureServer/0",
}

# Point geometry is cheap — pages of 1000 fit under the ArcGIS limit
# and well under any urllib timeout.
PAGE_SIZE = 1000


def _fetch_page(url: str, where: str, offset: int) -> dict:
    """Single-page fetch with f=json (we don't need GeoJSON envelopes
    for points — lat/lon are in the attributes already)."""
    q = urllib.parse.urlencode({
        "where": where,
        "outFields": "*",
        "f": "json",
        "resultOffset": offset,
        "resultRecordCount": PAGE_SIZE,
        "orderByFields": "OBJECTID",
    })
    full = f"{url}/query?{q}"
    req = urllib.request.Request(full, headers={
        "Accept-Encoding": "identity",
    })
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _coerce_latlon(val) -> float | None:
    """ArcGIS LATITUDE / LONGITUDE on these layers come back as decimal
    strings ("32.89901" / "-80.04056"). Some are also stored as integers
    or numeric — handle all three."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _slim_navaid(attrs: dict, geom: dict | None) -> dict | None:
    ident = (attrs.get("IDENT") or "").strip().upper()
    if not ident:
        return None
    lat = _coerce_latlon(attrs.get("LATITUDE"))
    lon = _coerce_latlon(attrs.get("LONGITUDE"))
    # Some records have the coords in geometry instead of fields — fall back.
    if (lat is None or lon is None) and geom:
        lat = geom.get("y") if lat is None else lat
        lon = geom.get("x") if lon is None else lon
    if lat is None or lon is None:
        return None
    return {
        "kind": "vor",  # generic until classify_navaid_type maps TYPE_CODE
        "ident": ident,
        "name": (attrs.get("NAME") or "").strip(),
        "lat": float(lat),
        "lon": float(lon),
        "type_code": (attrs.get("TYPE_CODE") or "").strip(),
        "freq_mhz": (float(attrs["FREQUENCY"])
                     if attrs.get("FREQUENCY") not in (None, "")
                     else None),
        "elevation_ft": (float(attrs["ELEVATION"])
                          if attrs.get("ELEVATION") not in (None, "")
                          else None),
        "magvar_deg": (float(attrs["MAGVAR"])
                        if attrs.get("MAGVAR") not in (None, "")
                        else None),
    }


def _slim_fix(attrs: dict, geom: dict | None) -> dict | None:
    ident = (attrs.get("IDENT") or "").strip().upper()
    if not ident:
        return None
    # Only keep ICAO-style 5-letter fixes — typical pilot lookup pattern.
    # The endpoint also serves 1-2-letter MEAs and other artifacts we
    # don't want polluting search.
    if not (3 <= len(ident) <= 5):
        return None
    lat = _coerce_latlon(attrs.get("LATITUDE"))
    lon = _coerce_latlon(attrs.get("LONGITUDE"))
    if (lat is None or lon is None) and geom:
        lat = geom.get("y") if lat is None else lat
        lon = geom.get("x") if lon is None else lon
    if lat is None or lon is None:
        return None
    return {
        "kind": "fix",
        "ident": ident,
        "lat": float(lat),
        "lon": float(lon),
        "type_code": (attrs.get("TYPE_CODE") or "").strip(),
        "state": (attrs.get("STATE") or "").strip(),
    }


def fetch_layer(key: str, url: str, out: Path) -> int:
    print(f"  {key}: fetching from {url}")
    rows: list = []
    # ArcGIS caps any single query at 5000 records server-side. To get
    # past it we walk OBJECTID windows of 5000 and rely on the orderBy
    # to keep ordering deterministic.
    window_size = 5000
    window_start = 0
    while True:
        # Pull this 5000-row window 1000 rows at a time.
        where = (f"OBJECTID >= {window_start} AND "
                 f"OBJECTID < {window_start + window_size}")
        local_rows: list = []
        offset = 0
        while True:
            page = None
            for attempt in range(4):
                try:
                    page = _fetch_page(url, where, offset)
                    break
                except Exception as e:
                    wait = 2 ** attempt
                    print(f"    window {window_start}+{offset} attempt {attempt+1} "
                          f"failed: {e} — retry in {wait}s")
                    time.sleep(wait)
            if page is None:
                raise RuntimeError(
                    f"{key}: aborted at window {window_start}+{offset}")
            feats = page.get("features", [])
            if not feats:
                break
            local_rows.extend(feats)
            if len(feats) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
        if not local_rows:
            # Empty window — we've walked past the last record.
            break
        for f in local_rows:
            attrs = f.get("attributes") or {}
            geom = f.get("geometry")
            slim = (_slim_navaid if key == "navaids" else _slim_fix)(attrs, geom)
            if slim is not None:
                rows.append(slim)
    # NavaidComponents stores VOR + DME at the same site as separate
    # rows with identical IDENT / lat / lon. Dedupe so search doesn't
    # show the same NAVAID twice. Hash on rounded lat/lon to absorb
    # the rare float-precision difference between sibling components.
    if key == "navaids":
        seen: set = set()
        deduped: list = []
        for r in rows:
            key_tuple = (r["ident"], round(r["lat"], 4), round(r["lon"], 4))
            if key_tuple in seen:
                continue
            seen.add(key_tuple)
            deduped.append(r)
        rows = deduped
        print(f"    window {window_start}..{window_start + window_size}: "
              f"got {len(local_rows)} raw → {len(rows)} kept so far …")
        window_start += window_size

    out.write_text(json.dumps(rows, separators=(",", ":")))
    size_kb = out.stat().st_size / 1024.0
    print(f"  {key}: wrote {len(rows)} records → {out} ({size_kb:.0f} KB)")
    return len(rows)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {OUT_DIR}")
    total = 0
    for key, url in LAYERS.items():
        out = OUT_DIR / f"{key}.json"
        total += fetch_layer(key, url, out)
    print(f"\nDone. {total} total records across {len(LAYERS)} layers.")


if __name__ == "__main__":
    sys.exit(main())
