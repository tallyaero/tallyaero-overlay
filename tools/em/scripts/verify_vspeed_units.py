"""Phase 2i — verify V-speed unit storage against parsed TCDS source data.

For every aircraft JSON we cross-reference its `tcds_number` against the
parsed TCDS files in `data/sources/tcds_parsed/`, which carry explicit
`unit` fields per V-speed. Three outcomes per aircraft:

  - MATCH_KIAS  : stored Vne ≈ TCDS-knots value (already correct)
  - MATCH_MPH   : stored Vne ≈ TCDS-mph value (NEEDS conversion ÷ 1.15078)
  - NO_MATCH    : stored value doesn't match either (manual review)
  - NO_TCDS     : aircraft has no matching parsed TCDS file (no verification)

Read-only. Print a report. The conversion script (`fix_vspeed_units.py`)
should be edited to only include aircraft that this script reports as
MATCH_MPH with high confidence.

Run: venv/bin/python scripts/verify_vspeed_units.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AIRCRAFT_DIR = ROOT / "aircraft_data"
TCDS_PARSED  = ROOT / "data" / "sources" / "tcds_parsed"
TCDS_MAPPING = ROOT / "docs" / "tcds_mapping.json"

KTS_TO_MPH = 1.15078
TOLERANCE  = 0.05  # 5% slop for rounding + variant-to-variant differences


def _load_filename_to_tcds() -> dict[str, str]:
    """Return {filename: tcds_number} from docs/tcds_mapping.json.
    Bridges aircraft JSONs that don't have a `tcds_number` field directly."""
    if not TCDS_MAPPING.exists():
        return {}
    try:
        rows = json.loads(TCDS_MAPPING.read_text())
    except Exception:
        return {}
    out: dict[str, str] = {}
    for r in rows:
        fn = r.get("filename")
        tn = r.get("tcds_number")
        if fn and tn:
            out[fn] = tn
    return out


def _load_tcds(tcds_number: str | None) -> dict | None:
    if not tcds_number:
        return None
    # The parsed TCDS filenames use the exact TCDS number with no leading "A-"
    candidates = [
        tcds_number,
        tcds_number.replace(" ", ""),
        tcds_number.replace("A-", ""),
    ]
    for c in candidates:
        p = TCDS_PARSED / f"{c}.json"
        if p.exists():
            return json.loads(p.read_text())
    return None


def _tcds_vne_values(tcds_data: dict) -> list[tuple[float, str]]:
    """Return (value, unit) pairs for every Vne across all variants."""
    out: list[tuple[float, str]] = []
    for v in tcds_data.get("variants", []):
        vs = v.get("v_speeds_kcas") or v.get("v_speeds") or {}
        vne = vs.get("Vne")
        if isinstance(vne, dict) and vne.get("value") is not None:
            try:
                val = float(vne["value"])
                unit = str(vne.get("unit", "")).lower()
                out.append((val, unit))
            except (TypeError, ValueError):
                pass
    return out


def _classify(stored: float, candidates: list[tuple[float, str]]) -> tuple[str, dict]:
    """Compare stored Vne to TCDS candidates; return verdict + match details."""
    if not candidates:
        return "NO_TCDS_VNE", {}
    best_kias = None
    best_mph  = None
    for val, unit in candidates:
        if "knot" in unit or "kt" in unit:
            best_kias = val if best_kias is None or abs(val - stored) < abs(best_kias - stored) else best_kias
        elif "mph" in unit:
            best_mph = val if best_mph is None or abs(val - stored) < abs(best_mph - stored) else best_mph

    rel = lambda a, b: abs(a - b) / max(a, 1) if a and b else 1
    if best_kias is not None and rel(stored, best_kias) <= TOLERANCE:
        return "MATCH_KIAS", {"tcds_kias": best_kias, "stored": stored}
    if best_mph  is not None and rel(stored, best_mph) <= TOLERANCE:
        return "MATCH_MPH", {"tcds_mph": best_mph, "stored": stored,
                              "kias_equivalent": round(stored / KTS_TO_MPH)}
    return "NO_MATCH", {
        "tcds_kias_candidates": [(v, u) for v, u in candidates if "knot" in u or "kt" in u],
        "tcds_mph_candidates":  [(v, u) for v, u in candidates if "mph" in u],
        "stored": stored,
    }


def main() -> int:
    fn_to_tcds = _load_filename_to_tcds()
    results = {
        "MATCH_KIAS": [],
        "MATCH_MPH":  [],
        "NO_MATCH":   [],
        "NO_TCDS_VNE": [],
        "NO_TCDS":    [],
    }
    for path in sorted(AIRCRAFT_DIR.glob("*.json")):
        try:
            d = json.loads(path.read_text())
        except Exception:
            continue
        name = d.get("name", path.stem)
        vne_stored = d.get("Vne")
        # Prefer the aircraft's own tcds_number field; fall back to the
        # filename-keyed mapping for aircraft that pre-date the Phase 2a edit.
        tcds_num = d.get("tcds_number") or fn_to_tcds.get(path.name)
        if vne_stored is None:
            continue
        tcds = _load_tcds(tcds_num)
        if not tcds:
            results["NO_TCDS"].append((name, tcds_num, vne_stored))
            continue
        candidates = _tcds_vne_values(tcds)
        verdict, detail = _classify(float(vne_stored), candidates)
        results[verdict].append((name, tcds_num, vne_stored, detail))

    print(f"\n{'='*70}")
    print("V-SPEED UNIT VERIFICATION — Vne cross-checked vs parsed TCDS")
    print(f"{'='*70}\n")
    print(f"  MATCH_KIAS  (already correct):   {len(results['MATCH_KIAS']):4d}")
    print(f"  MATCH_MPH   (need conversion):   {len(results['MATCH_MPH']):4d}")
    print(f"  NO_MATCH    (manual review):     {len(results['NO_MATCH']):4d}")
    print(f"  NO_TCDS_VNE (TCDS lacks Vne):    {len(results['NO_TCDS_VNE']):4d}")
    print(f"  NO_TCDS     (no parsed TCDS):    {len(results['NO_TCDS']):4d}\n")

    print(f"{'─'*70}")
    print("MATCH_MPH — stored value matches the TCDS MPH column (CONVERT)")
    print(f"{'─'*70}")
    for name, tcds_num, vne, detail in sorted(results["MATCH_MPH"]):
        print(f"  {name:32s} TCDS={tcds_num:10s} stored={vne:>5}  "
              f"TCDS_MPH={detail['tcds_mph']:>5g} → KIAS={detail['kias_equivalent']}")

    if results["NO_MATCH"]:
        print(f"\n{'─'*70}")
        print("NO_MATCH — needs manual review")
        print(f"{'─'*70}")
        for name, tcds_num, vne, detail in sorted(results["NO_MATCH"]):
            kias = ", ".join(f"{v}{u}" for v, u in detail.get("tcds_kias_candidates", [])) or "—"
            mph  = ", ".join(f"{v}{u}" for v, u in detail.get("tcds_mph_candidates",  [])) or "—"
            print(f"  {name:32s} TCDS={tcds_num:10s} stored={vne}")
            print(f"    TCDS knots candidates: {kias}")
            print(f"    TCDS mph   candidates: {mph}")

    if results["MATCH_KIAS"]:
        print(f"\n{'─'*70}")
        print(f"MATCH_KIAS — already correct (sample of first 10 of {len(results['MATCH_KIAS'])})")
        print(f"{'─'*70}")
        for name, tcds_num, vne, detail in sorted(results["MATCH_KIAS"])[:10]:
            print(f"  {name:32s} TCDS={tcds_num:10s} stored={vne}  TCDS_KIAS={detail['tcds_kias']:g}")

    if results["NO_TCDS"]:
        print(f"\n{'─'*70}")
        print(f"NO_TCDS — no parsed source ({len(results['NO_TCDS'])} aircraft, "
              f"e.g. warbirds, experimentals)")
        print(f"{'─'*70}")
        for name, tcds_num, vne in sorted(results["NO_TCDS"])[:20]:
            print(f"  {name:32s} TCDS={str(tcds_num):14s} stored Vne={vne}")
        if len(results["NO_TCDS"]) > 20:
            print(f"  …and {len(results['NO_TCDS']) - 20} more")

    return 0


if __name__ == "__main__":
    sys.exit(main())
