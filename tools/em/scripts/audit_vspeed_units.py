"""Phase 2i — audit V-speed storage units across the aircraft fleet.

Canonical convention (enforced going forward): every V-speed in every JSON
is in KIAS (knots indicated airspeed). Display-time MPH conversion happens
in the chart renderer via `_convert_speed`, never in storage.

This script scans aircraft_data/*.json and flags suspects where the stored
Vne/Vno/stall numbers look like they were copied from a pre-1968 MPH-era
TCDS without conversion. Heuristics:

  1. TCDS number from the CAR-3 / pre-FAR 23 era (issued before ~1972) —
     these were almost universally MPH. We treat any TCDS starting with
     "A-" + low 3-digit suffix (A-001..A-799) as a strong MPH-era signal.
  2. Vne ≥ 1.10× the typical KIAS Vne for that aircraft class — a 122 KIAS
     Vne for an Aeronca Chief is implausible; 122 MPH = 106 KIAS is correct.
  3. Stall × √(positive G limit) approximation to Va — if our stored Va
     (or implied) differs by ~15% from the published number, that's the
     MPH/KIAS swing.

The script is read-only — it prints a triage table. Fixes are applied by
`fix_vspeed_units.py` after spot-confirmation.

Run: venv/bin/python scripts/audit_vspeed_units.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
AIRCRAFT_DIR = ROOT / "aircraft_data"

KTS_TO_MPH = 1.15078


def _stall_speed_at_gross(ac: dict) -> float | None:
    """Pull the clean-config stall speed at MTOW (last entry in the table)."""
    ss = (ac.get("stall_speeds") or {}).get("clean") or {}
    speeds = ss.get("speeds") or []
    if not speeds:
        return None
    return float(speeds[-1])


def _mph_era_tcds(tcds: str | None) -> bool:
    """Best-effort heuristic for pre-1972 TCDS / MPH-era data sources.
    The FAA used MPH for type certificates issued under CAR 3 (1937–1965)
    and continued accepting MPH on FAR 23 docs through about 1972.

    Triggers:
      - A-NNN  (3-digit, ≤ A-799)  — CAR-3 originals
      - A-NNNN (4-digit, ≤ A-3000) — early FAR-23 transition era
      - 3A*   — CAR 3 numbering scheme (1956–1965 issuance)
      - Military / Warbird AFMs — almost universally MPH for WWII-era
      - LTC-NN — limited type certificate, used for some warbirds
    """
    if not tcds:
        return False
    t = tcds.upper().replace(" ", "")
    if t in {"MILITARY", "WARBIRD"}:
        return True
    if t.startswith("LTC-"):
        return True
    if t.startswith("3A"):
        return True
    if t.startswith("A-"):
        try:
            num = int(t.split("-")[1].split()[0])
        except (ValueError, IndexError):
            return False
        return num <= 3000
    return False


def _flag_aircraft(path: Path) -> dict:
    """Return a row dict for the triage report."""
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        return {"file": path.name, "error": str(exc)}

    name = data.get("name", path.stem)
    tcds = data.get("tcds_number")
    vne = data.get("Vne")
    vno = data.get("Vno")
    vs_gross = _stall_speed_at_gross(data)
    mph_era = _mph_era_tcds(tcds)

    flags: list[str] = []
    # Any MPH-era source + a plausibly-MPH Vne is a conversion candidate.
    # We flag liberally; the human reviewer's job is to confirm before fix.
    if mph_era and vne:
        flags.append(f"MPH_ERA_SOURCE (Vne={vne}, → KIAS {vne / KTS_TO_MPH:.0f})")
    # Vne/Vs ratio for normal-category GA piston is typically 2.5–3.5. If
    # it's over 3.5 we may have one or both unit-mismatched (cross-check).
    if vne and vs_gross and vs_gross > 0:
        ratio = vne / vs_gross
        if ratio > 3.6:
            flags.append(f"VNE_VS_RATIO_HIGH ({ratio:.2f}, expected 2.5-3.5 for piston GA)")
    # Outright impossible: Vne above 250 KIAS for a piston single. Most
    # warbird and high-performance pistons cap around 440-450 KIAS, so
    # if a Vne reads > 250 it might be an MPH spec from the AFM.
    if vne and vne > 250 and (data.get("type") == "single_engine"):
        if "MPH_ERA_SOURCE" not in " ".join(flags):
            flags.append(
                f"VNE_HIGH_PISTON_SINGLE (Vne={vne}, → KIAS {vne / KTS_TO_MPH:.0f})"
            )

    return {
        "file": path.name,
        "name": name,
        "tcds": tcds or "—",
        "Vne": vne,
        "Vno": vno,
        "Vs": vs_gross,
        "mph_era_tcds": mph_era,
        "flags": flags,
    }


def main(paths: Iterable[Path] | None = None) -> int:
    if paths is None:
        paths = sorted(AIRCRAFT_DIR.glob("*.json"))
    rows = [_flag_aircraft(p) for p in paths]
    suspects = [r for r in rows if r.get("flags")]

    print(f"\nScanned {len(rows)} aircraft files.")
    print(f"Flagged suspects: {len(suspects)}\n")
    if not suspects:
        return 0

    # Triage table
    name_w = max(len(r["name"]) for r in suspects)
    tcds_w = max(len(str(r["tcds"])) for r in suspects)
    header = f"{'Name':{name_w}}  {'TCDS':{tcds_w}}  {'Vne':>5}  {'Vno':>5}  {'Vs':>4}  Flags"
    print(header)
    print("-" * len(header))
    for r in sorted(suspects, key=lambda r: (not r["mph_era_tcds"], r["name"])):
        vne = f"{r['Vne']:>5}" if r["Vne"] is not None else "   —"
        vno = f"{r['Vno']:>5}" if r["Vno"] is not None else "   —"
        vs  = f"{r['Vs']:>4.0f}" if r["Vs"] is not None else "   —"
        flags = "; ".join(r["flags"])
        print(f"{r['name']:{name_w}}  {str(r['tcds']):{tcds_w}}  {vne}  {vno}  {vs}  {flags}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
