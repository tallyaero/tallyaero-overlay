"""
Apply the TCDS lookup table (docs/tcds_mapping.json) to every aircraft JSON.

For each entry: write `tcds_number`, `tcds_holder`, append a `Source` to
`sources[]`, and set `confidence = "partial"` (we have a citation but haven't
reconciled every numeric field against the source yet — that's Phase 2c).

Idempotent: safe to re-run after re-matching. The existing sources list is
not duplicated — we only insert the TCDS citation if it's not already there.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AIRCRAFT_DIR = REPO_ROOT / "aircraft_data"
MAPPING = REPO_ROOT / "docs" / "tcds_mapping.json"


def _source_key(s: dict) -> str:
    """Identity for deduplication."""
    return s.get("publication", "").strip()


def apply():
    rows = json.loads(MAPPING.read_text())
    by_file = {r["filename"]: r for r in rows}

    summary = {"verified": 0, "partial": 0, "estimated": 0, "skipped": 0, "total": 0}
    for path in sorted(AIRCRAFT_DIR.glob("*.json")):
        summary["total"] += 1
        mapping = by_file.get(path.name)
        if not mapping or not mapping.get("publication"):
            summary["skipped"] += 1
            continue

        ac = json.loads(path.read_text())

        # Inject TCDS metadata
        ac["tcds_number"] = mapping.get("tcds_number") or None
        ac["tcds_holder"] = mapping.get("tcds_holder") or None

        # Build the source citation
        new_source = {
            "publication": mapping["publication"],
            "retrieved": str(date.today()),
        }

        # Dedup: don't append if already present (by publication string)
        sources = ac.get("sources") or []
        existing_keys = {_source_key(s) for s in sources}
        if _source_key(new_source) not in existing_keys:
            sources.append(new_source)
        ac["sources"] = sources

        # Confidence: "partial" means we have a citation but haven't
        # reconciled every numeric field yet. Phase 2c upgrades this to
        # "verified" for aircraft where PDF parsing confirms the values.
        if not ac.get("confidence") or ac["confidence"] == "estimated":
            ac["confidence"] = "partial"

        summary[ac["confidence"]] = summary.get(ac["confidence"], 0) + 1

        # Pretty-print with stable key order
        path.write_text(json.dumps(ac, indent=2, ensure_ascii=False) + "\n")

    print(f"Migrated {summary['total']} aircraft profiles")
    print(f"  partial:   {summary.get('partial', 0)}   (has TCDS citation, not yet field-reconciled)")
    print(f"  verified:  {summary.get('verified', 0)}  (already field-reconciled — preserved)")
    print(f"  estimated: {summary.get('estimated', 0)} (no TCDS — placeholder only)")
    print(f"  skipped:   {summary['skipped']} (no mapping row)")


if __name__ == "__main__":
    apply()
