"""scripts/sync_check.py — diff aircraft_data/ between this repo and the
EM Diagram archive. Reports drift; does NOT mutate.

Run:
    venv/bin/python scripts/sync_check.py
    venv/bin/python scripts/sync_check.py --aircraft Cessna_172P    # one file only
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

OVERLAY_ROOT = Path("/Users/nicholaslen/Desktop/tallyaero_overlay_archives/aircraft_data")
EM_DIAGRAM_ROOT = Path("/Users/nicholaslen/Desktop/tallyaero_archives/aeroedge_em_diagram/aircraft_data")


def _hash(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--aircraft", help="Inspect a single aircraft basename (e.g. Cessna_172P)")
    args = p.parse_args()

    if not OVERLAY_ROOT.exists() or not EM_DIAGRAM_ROOT.exists():
        raise SystemExit("Either repo root not found; check paths.")

    if args.aircraft:
        names = [args.aircraft]
    else:
        names = sorted({p.stem for p in OVERLAY_ROOT.glob("*.json")}
                       | {p.stem for p in EM_DIAGRAM_ROOT.glob("*.json")})

    same = 0
    differ = []
    overlay_only = []
    em_only = []

    for name in names:
        ov = OVERLAY_ROOT / f"{name}.json"
        em = EM_DIAGRAM_ROOT / f"{name}.json"
        if ov.exists() and em.exists():
            if _hash(ov) == _hash(em):
                same += 1
            else:
                differ.append(name)
        elif ov.exists():
            overlay_only.append(name)
        else:
            em_only.append(name)

    print(f"identical: {same}")
    print(f"differ:    {len(differ)}")
    if differ:
        for n in differ[:20]:
            print(f"  - {n}")
        if len(differ) > 20:
            print(f"  ... and {len(differ) - 20} more")
    print(f"overlay-only: {len(overlay_only)}")
    for n in overlay_only[:10]:
        print(f"  - {n}")
    print(f"em-diagram-only: {len(em_only)}")
    for n in em_only[:10]:
        print(f"  - {n}")


if __name__ == "__main__":
    main()
