#!/usr/bin/env python3
"""Populate runway_end.pattern_direction in airports/airports.json from
the FAA Chart Supplement.

Source: FAA Chart Supplement text files (already downloaded into
tallyaero/z3_dashtwo_OLD/content-pipeline/output/chart-supplement/).
Each *.txt file covers a region. Within each file, airports are
delimited by their headers and runway-end lines say "Rgt tfc" when
right-hand pattern is published for that end. Absence of "Rgt tfc"
on an end means standard LEFT.

Airport headers look like:
    MYRTLE BEACH INTL
    (MYR)(KMYR)
    3 SW

Runway-end lines look like:
    RWY 18: MALSR. PAPI(P4L)—GA 3.0º TCH 64´. RVR–TR P–line. Rgt tfc.
    RWY 36: MALSF. PAPI(P4L)—GA 3.0º TCH 71´. RVR–TR Trees.

After running, every runway end in airports/airports.json that was
referenced by a chart supplement entry gets `pattern_direction:
"left"` or `"right"`. Ends with no chart supplement coverage stay as
they were (None / unspecified) — those default to LEFT at render
time with the amber "verify supplement" advisory.

Usage:
    python3 scripts/add_pattern_direction.py
    python3 scripts/add_pattern_direction.py --dry-run
    python3 scripts/add_pattern_direction.py --source /path/to/chart-supplement/

The script is idempotent — running it again replaces any previously
populated values with the current chart-supplement data.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from collections import defaultdict


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AIRPORTS_JSON = REPO_ROOT / "airports" / "airports.json"
DEFAULT_CHART_SUPPLEMENT_DIR = (
    REPO_ROOT.parent
    / "z3_dashtwo_OLD"
    / "content-pipeline"
    / "output"
    / "chart-supplement"
)

# Airport ID line — captures (LOCAL)(KXXXX) at the start of a line.
# Some entries only have (LOCAL), others have both, and the line can
# carry trailing class codes like "P (CG)" or "(CG) PR". We anchor
# only at the START so trailing content doesn't break the match.
_AIRPORT_ID_RE = re.compile(
    r"^\(([A-Z0-9]{3,4})\)(?:\(([A-Z0-9]{4})\))?(?:\s|$)"
)

# Runway-end line. Matches "RWY 18:" or "RWY 18L:" etc. Note that
# combined-end lines like "RWY 18–36:" are the PARENT runway header
# — we use the SINGLE-end form to associate "Rgt tfc" with that
# specific end. Match end identifiers as digits with optional
# L/R/C/W suffix and ignore any leading whitespace.
_RWY_END_RE = re.compile(
    r"^\s*RWY\s+([0-9]{1,2}[LRCW]?)\s*:\s*(.*)$"
)

# "Rgt tfc" inside an end's text — matches both with and without a
# trailing period and tolerates the unicode dash variants.
_RGT_TFC_RE = re.compile(r"\bR(?:gt|GT|ight)\s+(?:tfc|TFC|[Tt]raffic)\b")


def _normalize_runway_id(rwy_id: str) -> str:
    """Drop any leading zero on a runway-end identifier."""
    if not rwy_id:
        return rwy_id
    s = rwy_id.upper().strip()
    # "06" → "6" (we'll match either form against JSON later)
    return s


def parse_chart_supplement(directory: Path) -> dict[str, dict[str, str]]:
    """Walk every .txt file in `directory` and return a nested mapping:

        {airport_id: {runway_end_id: "left" | "right"}}

    `airport_id` is recorded under BOTH the local ID (e.g. "MYR") and
    the ICAO ID (e.g. "KMYR") so the merger can match against either
    convention.
    """
    out: dict[str, dict[str, str]] = defaultdict(dict)

    txt_files = sorted(directory.glob("*.txt"))
    if not txt_files:
        raise FileNotFoundError(
            f"No .txt files found in {directory}. "
            f"Pass --source to point at the chart-supplement dir.")

    print(f"Parsing {len(txt_files)} chart supplement files...")
    n_apts = 0
    n_rights = 0
    n_lefts = 0

    for fp in txt_files:
        try:
            lines = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue

        current_apt_ids: list[str] = []  # Maintain BOTH ICAO + local
        # Runway-end buffer — collects every line under the current
        # `RWY XX:` until the next runway end (or airport boundary)
        # so we catch "Rgt tfc" even when it's wrapped over multiple
        # lines (very common in the PDF→text dumps of the chart
        # supplement).
        rwy_buf_end_id: str | None = None
        rwy_buf_text: list[str] = []

        def flush_rwy_buffer():
            nonlocal n_rights, n_lefts
            if not rwy_buf_end_id or not current_apt_ids:
                return
            joined = " ".join(rwy_buf_text)
            if _RGT_TFC_RE.search(joined):
                direction = "right"
                n_rights += 1
            else:
                direction = "left"
                n_lefts += 1
            for apt_id in current_apt_ids:
                out[apt_id][rwy_buf_end_id] = direction

        for line in lines:
            # Airport id line — captures (LOCAL) or (LOCAL)(KICAO).
            m = _AIRPORT_ID_RE.match(line.strip())
            if m:
                # Boundary: flush the previous airport's last runway-end
                # buffer before switching context.
                flush_rwy_buffer()
                rwy_buf_end_id, rwy_buf_text = None, []

                local, icao = m.group(1), m.group(2)
                ids = [local]
                if icao:
                    ids.append(icao)
                if all(2 < len(x) <= 4 for x in ids):
                    current_apt_ids = ids
                    n_apts += 1
                continue

            # Runway-end line — start a new buffer.
            m = _RWY_END_RE.match(line)
            if m and current_apt_ids:
                # Flush previous end before starting new one.
                flush_rwy_buffer()
                rwy_id, rest = m.group(1), m.group(2)
                rwy_buf_end_id = _normalize_runway_id(rwy_id)
                rwy_buf_text = [rest]
                continue

            # Continuation line — append to current buffer if any.
            if rwy_buf_end_id is not None and line.strip():
                rwy_buf_text.append(line.strip())

        # Flush whatever's outstanding at end of file.
        flush_rwy_buffer()

    print(
        f"  parsed {n_apts} airport entries · "
        f"{n_rights} right-pattern runway ends · "
        f"{n_lefts} left/default ends"
    )
    return dict(out)


def merge_into_airports(airports_json_path: Path,
                         pattern_data: dict[str, dict[str, str]],
                         dry_run: bool = False) -> tuple[int, int, int]:
    """Update airports.json with parsed pattern directions.

    Returns (airports_matched, ends_updated_right, ends_updated_left).
    """
    print(f"Loading {airports_json_path}...")
    airports = json.loads(airports_json_path.read_text())
    print(f"  {len(airports)} airports loaded")

    matched_apts = 0
    set_right = 0
    set_left = 0

    for ap in airports:
        # Try local-only (e.g. "MYR") first, then ICAO ("KMYR"),
        # then the JSON's stored `id` (which is often a 2-letter
        # country prefix like "US-0001" — won't match anything in
        # the chart supplement and that's correct).
        candidates = [
            ap.get("local"),
            ap.get("icao"),
            ap.get("id"),
        ]
        match = None
        for c in candidates:
            if c and c in pattern_data:
                match = pattern_data[c]
                break
        if match is None:
            continue

        matched_apts += 1
        # Walk runways → ends; normalize end id for comparison.
        for rwy in ap.get("runways", []) or []:
            for end in rwy.get("ends", []) or []:
                end_id = _normalize_runway_id(end.get("id", ""))
                if not end_id:
                    continue
                direction = match.get(end_id)
                if direction is None:
                    # Try variants — sometimes JSON stores "06" vs
                    # parser stores "6" (or vice versa).
                    direction = (match.get(end_id.lstrip("0"))
                                 or match.get(end_id.zfill(2)))
                if direction is None:
                    continue
                end["pattern_direction"] = direction
                if direction == "right":
                    set_right += 1
                else:
                    set_left += 1

    print(
        f"  matched {matched_apts} airports · "
        f"set {set_right} right-pattern + {set_left} left-pattern ends"
    )

    if dry_run:
        print("DRY RUN — not writing to disk.")
    else:
        backup = airports_json_path.with_suffix(".json.bak")
        if not backup.exists():
            backup.write_text(airports_json_path.read_text())
            print(f"  wrote backup → {backup}")
        airports_json_path.write_text(
            json.dumps(airports, separators=(",", ":")))
        print(f"  wrote {airports_json_path}")

    return matched_apts, set_right, set_left


def main():
    ap = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path,
                     default=DEFAULT_CHART_SUPPLEMENT_DIR,
                     help="Directory containing FAA Chart Supplement .txt files")
    ap.add_argument("--airports", type=Path,
                     default=DEFAULT_AIRPORTS_JSON,
                     help="Path to airports/airports.json")
    ap.add_argument("--dry-run", action="store_true",
                     help="Don't write changes; just report what would happen")
    args = ap.parse_args()

    if not args.source.exists():
        print(f"ERROR: chart-supplement source not found: {args.source}",
              file=sys.stderr)
        return 2
    if not args.airports.exists():
        print(f"ERROR: airports JSON not found: {args.airports}",
              file=sys.stderr)
        return 2

    pattern_data = parse_chart_supplement(args.source)
    merge_into_airports(args.airports, pattern_data, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
