"""Phase 2i extended — handle the deferred cases (mismatches, km/h, nulls).

The first-pass fix script (`fix_vspeed_units.py`) only converted aircraft
where stored ≈ published (clean MPH cases). This handles the rest based
on the same primary-source research:

  • MPH mismatches  — stored ≠ published; trust published value
  • km/h cases      — original Luftwaffe/IJN km/h, agent computed KIAS
  • NULL fills      — Vne was missing; insert the researched value
  • DEFER           — genuinely ambiguous, leave alone

For mismatch cases we don't apply ÷1.15078 to ALL V-speeds (since the
stored values are inconsistent with the published baseline anyway).
Instead we update only Vne to `kias_equivalent`, leave Vno/stalls/arcs
alone, and tag `vspeeds_published_units` with the actual published unit
so the provenance trail records the discrepancy.

Run: venv/bin/python scripts/fix_vspeed_units_ext.py [--apply]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "_data" / "aircraft_data"
RESEARCH = ROOT / "docs" / "vne_unit_research.json"


# Explicit per-aircraft action plan derived from the research findings.
# Each tuple is (filename_stem, action, target_kias, published_unit).
# action ∈ {"overwrite_vne", "fill_null"}.
ACTIONS: list[tuple[str, str, int, str]] = [
    # ── MPH mismatches: trust published value, overwrite Vne only ────────
    ("Beechcraft_Sierra",      "overwrite_vne", 152, "MPH"),
    ("Cessna_177",             "overwrite_vne", 161, "MPH"),
    ("PT-17_Stearman",         "overwrite_vne", 162, "MPH"),
    ("Van's_RV-6",             "overwrite_vne", 182, "MPH"),
    ("Van's_RV-8",             "overwrite_vne", 200, "MPH"),
    ("Van's_RV-9A",            "overwrite_vne", 182, "MPH"),

    # ── km/h cases: convert per primary source ──────────────────────────
    ("Zlin_Z-242L",                  "overwrite_vne", 117, "km/h"),
    ("Focke-Wulf_FW_190_A-8",        "overwrite_vne", 405, "km/h"),
    ("Kawanishi_N1K2-J_Shiden-Kai",  "overwrite_vne", 400, "km/h"),
    ("Mitsubishi_A6M5_Zero",         "overwrite_vne", 356, "km/h"),
    ("Yakovlev_Yak-3",               "overwrite_vne", 378, "km/h"),

    # ── Warbirds whose stored value is MPH/km-h-equivalent ───────────────
    # (Research agent's "null" classification was a red herring — the JSONs
    # do have stored Vne. The values match the original AFM unit, not KIAS.)
    ("Messerschmitt Bf 109G-6",     "overwrite_vne", 405, "km/h"),
    ("North_American_P51-D_Mustang", "overwrite_vne", 439, "MPH"),
    ("Supermarine_Spitfire",        "overwrite_vne", 391, "MPH"),

    # Aviat Husky A-1C — genuinely ambiguous (stored 164 between agent's 132 kt
    # and modern POH ~145 KIAS). Defer; needs primary-source confirmation.
]


def _apply_action(data: dict, action: str, target_kias: int,
                  published_unit: str) -> list[str]:
    """Mutate `data` in place per the action plan. Returns a list of changes."""
    changes: list[str] = []
    if data.get("vspeeds_published_units"):
        return []                            # already touched

    if action == "fill_null":
        if data.get("Vne") is not None:
            return [f"  SKIP: Vne already set to {data.get('Vne')}"]
        data["Vne"] = target_kias
        changes.append(f"Vne: null → {target_kias} KIAS (from {published_unit} source)")
    elif action == "overwrite_vne":
        old = data.get("Vne")
        data["Vne"] = target_kias
        changes.append(f"Vne: {old} → {target_kias} KIAS (from {published_unit} source)")
    else:
        return [f"  SKIP: unknown action {action!r}"]

    data["vspeeds_published_units"] = published_unit
    sources = data.setdefault("sources", [])
    sources.append({
        "publication": (
            f"Phase 2i (extended) — Vne overwritten to {target_kias} KIAS "
            f"per primary-source research (originally published in {published_unit}). "
            "See docs/vne_unit_research.json for the cited source."
        ),
        "retrieved": "2026-05-15",
    })
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Write changes to disk. Without this, dry run.")
    args = parser.parse_args()

    total = 0
    missing = 0
    skipped = 0
    for stem, action, target_kias, unit in ACTIONS:
        path = DATA_DIR / f"{stem}.json"
        if not path.exists():
            print(f"  MISSING: {path}")
            missing += 1
            continue
        data = json.loads(path.read_text())
        changes = _apply_action(data, action, target_kias, unit)
        if not changes:
            print(f"  SKIP {stem}: already touched")
            skipped += 1
            continue
        # SKIP message via apply_action returns 1-element list starting with "  SKIP"
        if len(changes) == 1 and changes[0].startswith("  SKIP"):
            print(f"\n{stem} ({action}) — {changes[0]}")
            skipped += 1
            continue
        total += 1
        print(f"\n{stem} ({action})")
        for c in changes:
            print(f"  · {c}")
        if args.apply:
            path.write_text(json.dumps(data, indent=2) + "\n")

    print(f"\n{'='*60}")
    print(f"{'APPLIED' if args.apply else 'DRY-RUN'}: "
          f"{total} aircraft updated, {skipped} skipped, {missing} missing")
    if not args.apply:
        print("Re-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
