"""
Phase 3a — Build merged airports.json from OurAirports + FAA NASR.

Sources (all pre-normalized in the TallyAero monorepo research cache):
    OurAirports                85,312 global records — CC-BY
    NASR APT_BASE              22,026 US records     — FAA NASR cycle 2026-05-14
    NASR APT_RWY + APT_RWY_END 19,667 US runway sets — FAA NASR cycle 2026-05-14

Pipeline:
    1. OurAirports is the global base. Filter to fixed-wing types
       (small/medium/large_airport + seaplane_base) — drops heliport,
       closed, balloonport (~36k records).
    2. For US records (iso_country == "US"), augment with NASR APT_BASE
       (city, state, ownership) when the ICAO matches.
    3. For records with a NASR LID match, splice in NASR runway depth
       (surface, lighting, gradient, end-pair lat/lons, alignment).
    4. Fall back to OurAirports runways for non-US airports — but we
       don't have those in the normalized cache yet, so non-US records
       ship with empty runway lists for now. (Phase 3e can mine the raw
       OurAirports runways.csv if needed.)

Schema preserves the old fields (id, name, lat, lon, elevation_ft,
runways) so `core.aircraft_loader.load_airport_data` keeps working
without changes. Everything else is additive.

Idempotent: re-running with the same inputs writes the same output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE = Path("/Users/nicholaslen/Desktop/tallyaero/website/.research-cache/normalized")
OA_PATH    = CACHE / "ourairports.json"
NASR_PATH  = CACHE / "nasr-apt.json"
RWY_PATH   = CACHE / "nasr-runways.json"
OUT_PATH   = REPO_ROOT / "airports" / "airports.json"

KEEP_TYPES = {"small_airport", "medium_airport", "large_airport", "seaplane_base"}

# NASR surface codes → simple categories the rest of the app can reason about.
# Compound codes (ASPH-CONC) take the first segment.
SURFACE_MAP = {
    "ASPH": "asphalt",  "ASPHALT": "asphalt",
    "CONC": "concrete",
    "TURF": "turf",     "GRASS": "turf",   "SOD": "turf",
    "GRVL": "gravel",   "GRAVEL": "gravel",
    "DIRT": "dirt",     "CALICHE": "dirt", "SAND": "dirt",
    "WATER": "water",
    "WOOD":  "other",   "ALUMINUM": "other", "ALUM": "other",
    "METAL": "other",   "STEEL": "other",  "MATS": "other",
    "BRICK": "other",   "PEM":   "other",  "PSP":  "other",
    "ROOF-TOP": "other","ROOFTOP": "other","DECK": "other",
    "TRTD":  "other",   "TREATED": "other","SNOW": "other",
    "CORAL": "other",   "PFC": "other",
}


def norm_surface(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    head = code.split("-", 1)[0].split("/", 1)[0].strip().upper()
    return SURFACE_MAP.get(head, "other")


def strip_nulls(d: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is None, empty string, or empty list."""
    return {k: v for k, v in d.items() if v not in (None, "", [])}


def transform_runway(nasr_rwy: Dict[str, Any]) -> Dict[str, Any]:
    """Convert one NASR-runway record into our shape."""
    ends_in = nasr_rwy.get("ends") or []
    ends_out: List[Dict[str, Any]] = []
    for e in ends_in:
        ends_out.append(strip_nulls({
            "id":           e.get("id"),
            "lat":          e.get("lat"),
            "lon":          e.get("lon"),
            "elevation_ft": e.get("elev"),
            "heading":      e.get("alignment"),  # magnetic, matches old field name
            "ils":          e.get("ils"),
        }))
    return strip_nulls({
        "id":            nasr_rwy.get("rwyId"),
        "length_ft":     nasr_rwy.get("length"),
        "width_ft":      nasr_rwy.get("width"),
        "surface":       norm_surface(nasr_rwy.get("surface")),
        "lighting":      nasr_rwy.get("lighting"),
        "gradient_pct":  nasr_rwy.get("gradPct"),
        "ends":          ends_out,
    })


def main() -> None:
    oa   = json.loads(OA_PATH.read_text())["byId"]
    nasr = json.loads(NASR_PATH.read_text())["byId"]
    rwys = json.loads(RWY_PATH.read_text())["byAirport"]

    # NASR `byId` is double-indexed: ~2.6k major airports appear under both
    # their FAA LID ("AUS") and ICAO ("KAUS"), with the LID stored canonically
    # in the record's `lid` field. `nasr-runways` only keys by LID. Build an
    # ident-to-LID map from the record's internal `lid` so we always resolve
    # to the canonical key for the runway join.
    ident_to_lid: Dict[str, str] = {}
    for k, rec in nasr.items():
        lid = rec.get("lid")
        if not lid:
            continue
        ident_to_lid[lid] = lid
        icao = rec.get("icao")
        if icao:
            ident_to_lid[icao] = lid

    out: List[Dict[str, Any]] = []
    n_kept = n_us_aug = n_runways_aug = 0
    surface_counts: Dict[str, int] = {}

    for ident, ap in oa.items():
        if ap.get("type") not in KEEP_TYPES:
            continue
        n_kept += 1

        country = ap.get("iso_country")
        is_us = country == "US"

        # NASR base augment. The ident-to-LID map handles ICAO ("KAUS"→"AUS"),
        # direct LID ("00AA"→"00AA"), and the few small fields where OurAirports
        # uses a non-LID ident.
        nasr_rec: Dict[str, Any] = {}
        lid: Optional[str] = None
        if is_us:
            lid = ident_to_lid.get(ident)
            if lid:
                nasr_rec = nasr.get(lid) or {}
                n_us_aug += 1

        # Runways from NASR (if we have a LID match)
        runways_out: List[Dict[str, Any]] = []
        if lid:
            rwy_rec = rwys.get(lid)
            if rwy_rec and rwy_rec.get("runways"):
                for r in rwy_rec["runways"]:
                    # Filter out helipads at fixed-wing airports — NASR mixes
                    # them in (rwyId like "H1", "H2"). They're not relevant
                    # for the EM diagram's field-elevation lookup.
                    rwy_id = (r.get("rwyId") or "").upper()
                    if rwy_id.startswith("H"):
                        continue
                    rw = transform_runway(r)
                    runways_out.append(rw)
                    s = rw.get("surface") or "(none)"
                    surface_counts[s] = surface_counts.get(s, 0) + 1
                if runways_out:
                    n_runways_aug += 1

        # Prefer NASR elevation when present (more recent + authoritative for US)
        elevation_ft = nasr_rec.get("elev") if nasr_rec.get("elev") is not None else ap.get("elevation_ft")
        # ICAO heuristic: 4 letters, all alpha. Excludes things like "00AA".
        icao_val = ident if (len(ident) == 4 and ident.isalpha()) else None
        sched = ap.get("scheduled_service") == "yes"

        record = strip_nulls({
            # ---- backwards-compat (old loader reads these unchanged) ----
            "id":            ident,
            "name":          ap.get("name") or "",
            "lat":           ap.get("latitude_deg"),
            "lon":           ap.get("longitude_deg"),
            "elevation_ft":  elevation_ft,
            "runways":       runways_out,
            # ---- new fields ----
            "icao":          icao_val,
            "iata":          ap.get("iata_code"),
            "local":         lid or ap.get("local_code"),
            "country":       country,
            "region":        ap.get("iso_region"),
            "municipality":  ap.get("municipality") or (nasr_rec.get("city").title() if nasr_rec.get("city") else None),
            "state":         nasr_rec.get("state"),
            "type":          ap.get("type"),
            # Only emit scheduled_service when True (default False omitted to save bytes)
            "scheduled_service": True if sched else None,
            "wikipedia":     ap.get("wikipedia_link"),
        })
        out.append(record)

    # Stable sort: country, then id — keeps US block together for diff readability.
    out.sort(key=lambda r: (r.get("country") or "ZZ", r["id"]))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n")
    size_mb = OUT_PATH.stat().st_size / 1024 / 1024

    # Distribution summary
    from collections import Counter
    by_country = Counter(r.get("country") for r in out)
    by_type    = Counter(r.get("type") for r in out)
    with_runways = sum(1 for r in out if r.get("runways"))
    with_elev    = sum(1 for r in out if r.get("elevation_ft") is not None)

    print(f"Phase 3a — merged airports.json written")
    print(f"  output:           {OUT_PATH.relative_to(REPO_ROOT)}")
    print(f"  size on disk:     {size_mb:.1f} MB")
    print(f"  records:          {len(out):,}  (was 16,128 before)")
    print(f"  with elevation:   {with_elev:,}")
    print(f"  with runways:     {with_runways:,}")
    print(f"  US records aug'd by NASR base:    {n_us_aug:,}")
    print(f"  US records aug'd by NASR runways: {n_runways_aug:,}")
    print()
    print(f"Top countries (top 10):")
    for c, n in by_country.most_common(10):
        print(f"  {c or '(none)':<6} {n:>6,}")
    print()
    print(f"Type breakdown:")
    for t, n in by_type.most_common():
        print(f"  {t:<22} {n:>6,}")
    print()
    print(f"Runway surface mix:")
    for s, n in sorted(surface_counts.items(), key=lambda x: -x[1]):
        print(f"  {s:<10} {n:>6,}")


if __name__ == "__main__":
    main()
