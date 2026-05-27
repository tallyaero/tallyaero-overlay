#!/usr/bin/env python3
"""
TallyAero cross-app drift detector — Phase 7.

Walks the [Shared Asset Ledger] from EM_DIAGRAM_EXECUTION_PLAN.md side-by-side
between the EM Diagram tree and the overlay-tool tree. For each entry:

  - reports IDENTICAL    when content hashes match
  - reports DRIFT        when both exist but differ
  - reports EM-ONLY      when only the EM side has the file
  - reports OVERLAY-ONLY when only the overlay side has the file
  - reports MISSING      when neither side has it

Default behavior is read-only and verbose enough to drive a manual
reconciliation. `--apply em-to-overlay` copies the EM-side version on
top of the overlay's for any DRIFT or EM-ONLY entry (this is the
canonical direction during the EM phase). `--apply overlay-to-em`
exists for emergencies and requires `--force` to actually write.

Usage:
    python scripts/sync_check.py
    python scripts/sync_check.py --apply em-to-overlay
    python scripts/sync_check.py --apply overlay-to-em --force
    python scripts/sync_check.py --verbose            # show per-file rows for globs

Exit codes:
    0  no drift
    1  drift detected (or files missing)
    2  invocation error
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]

# The overlay tree path. The pytest snapshot test in tests/test_jsons.py
# uses the same lookup logic — keep these in sync if you ever move things.
_OVERLAY_CANDIDATES = [
    REPO_ROOT.parent / "tallyaero_overlay_tools",
    REPO_ROOT.parent / "aeroedge_overlay_tools",     # legacy pre-rename name
]
OVERLAY_ROOT = next((p for p in _OVERLAY_CANDIDATES if p.exists()), None)


# ---------------------------------------------------------------------------
# Shared Asset Ledger — mirrors §6 of EM_DIAGRAM_EXECUTION_PLAN.md.
# Each entry is either a single file or a glob pattern. If the EM path uses
# a glob, the overlay path must accept the same glob.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LedgerEntry:
    label:        str
    em_path:      str       # relative to REPO_ROOT
    overlay_path: str       # relative to OVERLAY_ROOT
    is_glob:      bool = False

LEDGER: list[LedgerEntry] = [
    # ── Physics / math core ──────────────────────────────────────────────
    LedgerEntry("Core calculations",      "core/calculations.py",  "core/calculations.py"),
    LedgerEntry("Vmca dynamic",           "core/vmca.py",          "core/vmca.py"),
    LedgerEntry("Vyse dynamic",           "core/vyse.py",          "core/vyse.py"),
    LedgerEntry("Constants",              "core/constants.py",     "core/constants.py"),
    LedgerEntry("Plotly themes",          "core/plotly_themes.py", "core/plotly_themes.py"),
    LedgerEntry("Aircraft schema",        "core/schema.py",        "core/schema.py"),
    LedgerEntry("Aircraft loader",        "core/aircraft_loader.py","core/aircraft_loader.py"),
    # ── Data ─────────────────────────────────────────────────────────────
    LedgerEntry("Aircraft JSONs",         "aircraft_data/*.json",  "aircraft_data/*.json", is_glob=True),
    LedgerEntry("Airport data",           "airports/airports.json","airports/airports.json"),
    # ── Visual identity ──────────────────────────────────────────────────
    LedgerEntry("Design tokens",          "assets/tokens.css",     "assets/tokens.css"),
    # ── Sync infrastructure (one canonical script in both trees) ─────────
    LedgerEntry("Sync check script",      "scripts/sync_check.py", "scripts/sync_check.py"),
]


# ---------------------------------------------------------------------------
# Status enum + result type
# ---------------------------------------------------------------------------
STATUS_OK         = "IDENTICAL"
STATUS_DRIFT      = "DRIFT"
STATUS_EM_ONLY    = "EM-ONLY"
STATUS_OVERLAY    = "OVERLAY-ONLY"
STATUS_MISSING    = "MISSING"

@dataclass
class FileResult:
    em_path:       Path | None
    overlay_path:  Path | None
    status:        str
    detail:        str = ""

@dataclass
class LedgerResult:
    label:    str
    entries:  list[FileResult] = field(default_factory=list)

    @property
    def drift_count(self) -> int:
        return sum(1 for e in self.entries if e.status in (STATUS_DRIFT, STATUS_EM_ONLY, STATUS_OVERLAY_ONLY := STATUS_OVERLAY))


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------
def _hash(path: Path) -> str:
    """SHA-256 of the file's bytes. Used as the drift identity check."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _compare(em_file: Path | None, ov_file: Path | None) -> FileResult:
    """Compare one file pair and return a FileResult."""
    if em_file and ov_file and em_file.exists() and ov_file.exists():
        h_em = _hash(em_file)
        h_ov = _hash(ov_file)
        if h_em == h_ov:
            return FileResult(em_file, ov_file, STATUS_OK)
        size_em = em_file.stat().st_size
        size_ov = ov_file.stat().st_size
        return FileResult(em_file, ov_file, STATUS_DRIFT, f"EM={size_em:,}B  OV={size_ov:,}B")
    if em_file and em_file.exists() and not (ov_file and ov_file.exists()):
        return FileResult(em_file, ov_file, STATUS_EM_ONLY, f"{em_file.stat().st_size:,}B")
    if ov_file and ov_file.exists() and not (em_file and em_file.exists()):
        return FileResult(em_file, ov_file, STATUS_OVERLAY, f"{ov_file.stat().st_size:,}B")
    return FileResult(em_file, ov_file, STATUS_MISSING)


def _resolve(entry: LedgerEntry) -> LedgerResult:
    """Resolve one ledger entry into one or more FileResults."""
    result = LedgerResult(label=entry.label)
    em_root = REPO_ROOT
    ov_root = OVERLAY_ROOT

    if entry.is_glob:
        # Union the basenames present in either tree, compare per file
        em_files = {p.name: p for p in em_root.glob(entry.em_path)}
        ov_files = {p.name: p for p in ov_root.glob(entry.overlay_path)} if ov_root else {}
        for name in sorted(set(em_files) | set(ov_files)):
            result.entries.append(_compare(em_files.get(name), ov_files.get(name)))
    else:
        em_p = em_root / entry.em_path
        ov_p = (ov_root / entry.overlay_path) if ov_root else None
        result.entries.append(_compare(em_p, ov_p))

    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _format_results(ledger_results: list[LedgerResult], verbose: bool) -> tuple[str, dict]:
    """Build the human report + a counts dict for the exit decision."""
    lines: list[str] = []
    counts = {STATUS_OK: 0, STATUS_DRIFT: 0, STATUS_EM_ONLY: 0, STATUS_OVERLAY: 0, STATUS_MISSING: 0}

    lines.append(f"\n{'Asset':<28} {'Status':<14} {'Detail':<40}")
    lines.append("-" * 90)

    for lr in ledger_results:
        if len(lr.entries) == 1:
            fr = lr.entries[0]
            counts[fr.status] += 1
            lines.append(f"{lr.label:<28} {fr.status:<14} {fr.detail}")
            continue
        # Glob: collapse repeated statuses into a single rolled-up row,
        # then explode per-file when --verbose.
        roll: dict[str, list[FileResult]] = {}
        for fr in lr.entries:
            counts[fr.status] += 1
            roll.setdefault(fr.status, []).append(fr)
        for status, frs in roll.items():
            lines.append(f"{lr.label:<28} {status:<14} {len(frs):>3} files")
            if verbose:
                for fr in frs[:25]:
                    nm = fr.em_path.name if fr.em_path else (fr.overlay_path.name if fr.overlay_path else "?")
                    lines.append(f"{'  · ' + nm:<28} {'':<14} {fr.detail}")
                if len(frs) > 25:
                    lines.append(f"{'  · …':<28} {'':<14} ({len(frs) - 25} more not shown)")
    lines.append("-" * 90)
    lines.append(f"Summary: {counts[STATUS_OK]} identical · {counts[STATUS_DRIFT]} drift · "
                  f"{counts[STATUS_EM_ONLY]} EM-only · {counts[STATUS_OVERLAY]} overlay-only · "
                  f"{counts[STATUS_MISSING]} missing")
    return "\n".join(lines), counts


# ---------------------------------------------------------------------------
# Apply (write EM → overlay or vice versa)
# ---------------------------------------------------------------------------
def _apply(ledger_results: list[LedgerResult], direction: str, force: bool) -> int:
    """Copy drifted/missing files from source → target. Returns # written."""
    written = 0
    if direction == "overlay-to-em" and not force:
        print("\nERROR: overlay-to-em apply requires --force.")
        print("       This direction overwrites the EM tree, which is canonical during the EM phase.")
        sys.exit(2)
    if not OVERLAY_ROOT:
        print("\nERROR: no overlay tree found at expected paths.")
        sys.exit(2)

    for lr in ledger_results:
        for fr in lr.entries:
            should_copy = False
            if direction == "em-to-overlay":
                # Copy EM → overlay when overlay differs or is missing
                if fr.status == STATUS_DRIFT or fr.status == STATUS_EM_ONLY:
                    should_copy = True
                src, dst = fr.em_path, fr.overlay_path
                if src is None:
                    continue
                if dst is None:
                    # Reconstruct dst path from the EM path's relative position
                    rel = src.relative_to(REPO_ROOT)
                    dst = OVERLAY_ROOT / rel
            else:                       # overlay-to-em
                if fr.status == STATUS_DRIFT or fr.status == STATUS_OVERLAY:
                    should_copy = True
                src, dst = fr.overlay_path, fr.em_path
                if src is None:
                    continue
                if dst is None:
                    rel = src.relative_to(OVERLAY_ROOT)
                    dst = REPO_ROOT / rel
            if not should_copy:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            print(f"  copied {src.relative_to(REPO_ROOT.parent) if src.is_relative_to(REPO_ROOT.parent) else src} → "
                  f"{dst.relative_to(REPO_ROOT.parent) if dst.is_relative_to(REPO_ROOT.parent) else dst}")
            written += 1
    return written


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else None,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", choices=["em-to-overlay", "overlay-to-em"],
                        help="Copy drifted/missing files in the given direction.")
    parser.add_argument("--force", action="store_true",
                        help="Required with --apply overlay-to-em.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Explode glob entries to per-file rows.")
    args = parser.parse_args()

    print(f"EM tree:      {REPO_ROOT}")
    print(f"Overlay tree: {OVERLAY_ROOT or '(NOT FOUND)'}")

    if OVERLAY_ROOT is None:
        print("\nNo overlay tree at the expected sibling paths:")
        for p in _OVERLAY_CANDIDATES:
            print(f"  - {p}")
        print("\nDrift can't be assessed without both sides.")
        return 2

    ledger_results = [_resolve(e) for e in LEDGER]
    report, counts = _format_results(ledger_results, verbose=args.verbose)
    print(report)

    if args.apply:
        n_written = _apply(ledger_results, direction=args.apply, force=args.force)
        print(f"\nApplied {n_written} change(s) in direction '{args.apply}'.")
        # Re-resolve after apply so the exit code reflects post-state
        ledger_results = [_resolve(e) for e in LEDGER]
        _, counts = _format_results(ledger_results, verbose=False)

    drift_total = counts[STATUS_DRIFT] + counts[STATUS_EM_ONLY] + counts[STATUS_OVERLAY] + counts[STATUS_MISSING]
    return 0 if drift_total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
