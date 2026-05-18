#!/usr/bin/env python3
"""Phase B2 — class-derived performance_dynamics for all 110 aircraft.

Walks aircraft_data/*.json and writes a `performance_dynamics` block
to each file with provenance="class_derived". Idempotent: skips files
whose existing block has provenance="poh" so Phase B3 hand-curated
values are never clobbered.

Classification heuristic (in priority order):
    top-tier aerobatic  aerobatic.clean.positive >= 8.0       roll=120
    aerobatic-trainer   normal.clean.positive >= 4.5          roll=90
    light twin          engine_count >= 2                     roll=25
    complex/retract     gear_type == "retractable", 1 engine  roll=35
    trainer 4-seat      seats >= 4, fixed/unknown gear        roll=45
    light single 2-seat default for everything else            roll=40

Run with --dry-run to print the classification table without writing.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
AIRCRAFT_DIR = REPO_ROOT / "aircraft_data"


def _gpos(ac: dict, category: str, config: str = "clean") -> float:
    """Helper: G_limits[category][config].positive, returns 0 if missing."""
    try:
        return float(ac["G_limits"][category][config]["positive"])
    except (KeyError, TypeError, ValueError):
        return 0.0


def _classify_roll_rate(ac: dict) -> int:
    """Pick a roll-rate class (deg/s) based on aircraft category signals."""
    aero_clean = _gpos(ac, "aerobatic", "clean")
    norm_clean = _gpos(ac, "normal", "clean")
    engine_count = int(ac.get("engine_count", 1))
    gear_type = ac.get("gear_type")
    seats = int(ac.get("seats", 2))

    # Tier 1: top-tier aerobatic (Pitts S-2C aero.clean=10, Extra 300 etc.)
    if aero_clean >= 8.0:
        return 120
    # Tier 2: aerobatic-trainer (Decathlon norm=5.0, Pitts S-1C aero.to=4.0)
    # Two signals:
    #   norm.clean.positive >= 4.5 (Decathlon, Citabria — genuinely
    #     elevated above the standard utility 4.4)
    #   OR aerobatic.takeoff.positive > 0 (real aerobatic certification —
    #     most non-acro aircraft have the all-zero takeoff sentinel)
    aero_to = _gpos(ac, "aerobatic", "takeoff")
    if norm_clean >= 4.5 or aero_to > 0:
        return 90
    # Tier 3: light twin
    if engine_count >= 2:
        return 25
    # Tier 4: complex/retract single
    if gear_type == "retractable" and engine_count == 1:
        return 35
    # Tier 5: trainer (4-seat fixed/unknown gear)
    if seats >= 4 and gear_type != "retractable":
        return 45
    # Tier 6: light single 2-seat default
    return 40


def _bank_tau(roll_rate_dps: int) -> float:
    """First-order roll-response time constant. τ ≈ 1.3 / ω where ω is
    max steady-state roll rate in rad/s."""
    return round(1.3 / (roll_rate_dps * math.pi / 180.0), 3)


def _speed_tau(ac: dict) -> float:
    """Longitudinal speed-response τ from gross weight.

    Simple model: heavier aircraft take longer to accelerate/decelerate
    to a new equilibrium speed. τ ≈ 1.0 + max_weight_lb / 2000, clamped
    to a plausible [1.0, 4.5] s range for GA singles and twins."""
    mw = float(ac.get("max_weight", 2500))
    tau = 1.0 + mw / 2000.0
    return round(max(1.0, min(4.5, tau)), 2)


def _takeoff_accel(ac: dict) -> float:
    """Dimensionless takeoff acceleration factor ≈ (P_avail / W) / Vlof.

    factor = (HP * 550 * η_prop) / (max_weight * Vlof_fps)
    where Vlof = Vs0_landing * 1.2 (or best_glide * 0.85 fallback)."""
    eng_opts = ac.get("engine_options") or {}
    # Sum horsepower across all installed engines (multi-engine support).
    if not eng_opts:
        hp = 180.0
    else:
        per_engine_hp = next(iter(eng_opts.values())).get("horsepower", 180.0)
        hp = float(per_engine_hp) * int(ac.get("engine_count", 1))
    mw = float(ac.get("max_weight", 2500))

    # Vlof: prefer landing-flap Vs0; fall back to best_glide * 0.85.
    vlof_kt = None
    stall_landing = ac.get("stall_speeds", {}).get("landing", {})
    speeds = stall_landing.get("speeds", []) if isinstance(stall_landing, dict) else []
    if speeds:
        vlof_kt = float(speeds[-1]) * 1.2  # at max weight
    else:
        bg = ac.get("single_engine_limits", {}).get("best_glide")
        if bg:
            vlof_kt = float(bg) * 0.85

    if not vlof_kt or vlof_kt <= 0:
        vlof_kt = 60.0  # generic fallback
    vlof_fps = vlof_kt * 1.68781

    factor = (hp * 550.0 * 0.85) / (mw * vlof_fps)
    # Clamp to schema range (0, 1.0].
    return round(min(1.0, max(0.05, factor)), 3)


def derive_dynamics(ac: dict[str, Any]) -> dict[str, Any]:
    """Pure: aircraft JSON dict → performance_dynamics dict.

    Sets provenance="class_derived" and poh_citation=None. Callers that
    want POH-tier values should overwrite the returned dict; the result
    of this function alone is never POH-tier."""
    roll = _classify_roll_rate(ac)
    return {
        "roll_rate_dps": float(roll),
        "bank_response_tau_s": _bank_tau(roll),
        "speed_response_tau_s": _speed_tau(ac),
        "takeoff_accel_factor": _takeoff_accel(ac),
        "inter_maneuver_pause_s": 1.0,
        "provenance": "class_derived",
        "poh_citation": None,
    }


def _process_file(path: Path, *, dry_run: bool) -> tuple[str, str]:
    """Returns (basename, summary_line). Writes the file unless dry_run."""
    with open(path) as f:
        data = json.load(f)
    name = data.get("name", path.stem)
    existing = data.get("performance_dynamics")
    if existing and existing.get("provenance") == "poh":
        return path.stem, f"{name}: SKIP (poh-curated)"
    pd = derive_dynamics(data)
    summary = (f"{name}: roll={pd['roll_rate_dps']:.0f} "
               f"τbank={pd['bank_response_tau_s']:.2f} "
               f"τspd={pd['speed_response_tau_s']:.2f} "
               f"TOacc={pd['takeoff_accel_factor']:.2f}")
    if not dry_run:
        data["performance_dynamics"] = pd
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
    return path.stem, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print classification table without writing files.")
    args = parser.parse_args()

    files = sorted(AIRCRAFT_DIR.glob("*.json"))
    if not files:
        print(f"No aircraft files found in {AIRCRAFT_DIR}", file=sys.stderr)
        sys.exit(1)

    for path in files:
        _, summary = _process_file(path, dry_run=args.dry_run)
        print(summary)

    mode = "DRY RUN" if args.dry_run else "APPLIED"
    print(f"\n[{mode}] {len(files)} aircraft processed.")


if __name__ == "__main__":
    main()
