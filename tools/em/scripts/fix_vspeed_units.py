"""Phase 2i — convert V-speeds from MPH-era source values to canonical KIAS.

Reads `docs/vne_unit_research.json` (produced by a research agent that
cross-referenced primary sources for each aircraft) and converts only the
"clean MPH" cases — where the stored Vne matches the primary-source MPH
value within tolerance. Everything else (mismatched, km/h, low-confidence)
is left untouched and surfaced in the report for manual review.

Conversion applied to every V-speed field per aircraft:
    Vne, Vno, Vfe.{takeoff,landing}, all stall_speeds.{flap}.speeds[],
    single_engine_limits.best_glide, prop_thrust_decay.V_max_kts, arcs.*

Provenance: adds `"vspeeds_published_units": "MPH"` + a sources entry
linking to the research findings. Idempotent.

Run: venv/bin/python scripts/fix_vspeed_units.py [--apply]
Without --apply this is a dry run; with --apply it writes the JSONs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AIRCRAFT_DIR = ROOT / "aircraft_data"
RESEARCH     = ROOT / "docs" / "vne_unit_research.json"

KTS_TO_MPH = 1.15078
STORED_MATCH_TOLERANCE = 0.03   # 3% slop between stored and published MPH


def _name_to_filename(name: str) -> str:
    """Translate human aircraft name to its JSON filename."""
    # The repo uses replace-space-with-underscore + keep punctuation
    return name.replace(" ", "_") + ".json"


def _load_eligible() -> list[dict]:
    """Pick aircraft from the research file that are safe to auto-convert."""
    if not RESEARCH.exists():
        raise SystemExit(f"missing research file: {RESEARCH}")
    rows = json.loads(RESEARCH.read_text())
    eligible: list[dict] = []
    for r in rows:
        unit = (r.get("published_unit") or "").lower()
        conf = (r.get("confidence")     or "").lower()
        stored = r.get("stored_vne")
        published = r.get("published_vne")
        if unit != "mph":              continue
        if conf == "low":              continue
        if stored is None or published is None: continue
        if abs(stored - published) / published > STORED_MATCH_TOLERANCE:
            continue
        eligible.append(r)
    return eligible


def _convert_value(v):
    """Apply MPH → KIAS conversion. Round to nearest integer for readability.
    None entries inside a list (e.g., `arcs.white: [null, 80]`) pass through
    unchanged — they're missing-data sentinels, not values."""
    if v is None:
        return None
    if isinstance(v, list):
        return [
            (round(float(x) / KTS_TO_MPH) if x is not None else None)
            for x in v
        ]
    return round(float(v) / KTS_TO_MPH)


def _convert_aircraft(data: dict, research_entry: dict) -> tuple[dict, list[str]]:
    """Apply the unit conversion to every V-speed field on this aircraft.
    Idempotent: skips if `vspeeds_published_units` is already set."""
    if data.get("vspeeds_published_units"):
        return data, []

    changes: list[str] = []

    for key in ("Vne", "Vno"):
        if key in data and data[key] is not None:
            old = data[key]
            data[key] = _convert_value(old)
            changes.append(f"{key}: {old} → {data[key]}")

    vfe = data.get("Vfe")
    if isinstance(vfe, dict):
        for k in ("takeoff", "landing"):
            if k in vfe and vfe[k] is not None:
                old = vfe[k]
                vfe[k] = _convert_value(old)
                changes.append(f"Vfe.{k}: {old} → {vfe[k]}")

    ss = data.get("stall_speeds")
    if isinstance(ss, dict):
        for flap, table in ss.items():
            if isinstance(table, dict) and "speeds" in table:
                old = list(table["speeds"])
                table["speeds"] = _convert_value(table["speeds"])
                changes.append(f"stall_speeds.{flap}.speeds: {old} → {table['speeds']}")

    sel = data.get("single_engine_limits")
    if isinstance(sel, dict) and "best_glide" in sel:
        old = sel["best_glide"]
        sel["best_glide"] = _convert_value(old)
        changes.append(f"single_engine_limits.best_glide: {old} → {sel['best_glide']}")

    ptd = data.get("prop_thrust_decay")
    if isinstance(ptd, dict) and "V_max_kts" in ptd:
        old = ptd["V_max_kts"]
        ptd["V_max_kts"] = _convert_value(old)
        changes.append(f"prop_thrust_decay.V_max_kts: {old} → {ptd['V_max_kts']}")

    arcs = data.get("arcs")
    if isinstance(arcs, dict):
        for arc_name, val in list(arcs.items()):
            if isinstance(val, list):
                old = list(val)
                arcs[arc_name] = _convert_value(val)
                changes.append(f"arcs.{arc_name}: {old} → {arcs[arc_name]}")
            elif isinstance(val, (int, float)):
                old = val
                arcs[arc_name] = _convert_value(val)
                changes.append(f"arcs.{arc_name}: {old} → {arcs[arc_name]}")

    # Provenance
    data["vspeeds_published_units"] = "MPH"
    sources = data.setdefault("sources", [])
    sources.append({
        "publication": (
            "Phase 2i unit-canonicalization: MPH → KIAS (÷ 1.15078). "
            f"Research source: {research_entry.get('source', 'docs/vne_unit_research.json')}. "
            f"Confidence: {research_entry.get('confidence', 'unknown')}."
        ),
        "retrieved": "2026-05-14",
    })

    return data, changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Write changes to disk. Without this, dry run.")
    args = parser.parse_args()

    eligible = _load_eligible()
    print(f"Eligible for auto-conversion (clean MPH, high/medium confidence,"
          f" stored matches published within {STORED_MATCH_TOLERANCE:.0%}):"
          f" {len(eligible)} aircraft\n")

    total = 0
    skipped = 0
    missing = 0
    for r in eligible:
        stem = _name_to_filename(r["name"]).removesuffix(".json")
        path = AIRCRAFT_DIR / f"{stem}.json"
        if not path.exists():
            # Try variants (apostrophes, hyphens, etc.)
            print(f"  MISSING file for {r['name']}  (looking for {path.name})")
            missing += 1
            continue
        data = json.loads(path.read_text())
        new_data, changes = _convert_aircraft(data, r)
        if not changes:
            print(f"  SKIP {stem}: already converted")
            skipped += 1
            continue
        total += 1
        print(f"\n{stem} — {r.get('source', '')[:80]}")
        for c in changes:
            print(f"  · {c}")
        if args.apply:
            path.write_text(json.dumps(new_data, indent=2) + "\n")

    print(f"\n{'='*60}")
    print(f"{'APPLIED' if args.apply else 'DRY-RUN'}: converted {total} aircraft "
          f"({skipped} already converted, {missing} files missing)")
    if not args.apply:
        print("Re-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
