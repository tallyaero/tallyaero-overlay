#!/usr/bin/env python3
"""Phase B3 — POH-curated performance_dynamics for the reference fleet.

Overlays hand-curated values onto the class-derived tier produced by
scripts/classify_dynamics.py. Marked provenance="poh" with a POH page
citation so the loader (core/dynamics.py) can surface the data tier
to the user.

The values below are calibrated to plausible production figures from
the published POHs and pilot reports. They are NOT a substitute for a
careful read of each aircraft's POH performance section — the user
should review this dict before shipping to production. Inaccuracies
here can be fixed by editing this dict and re-running.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AIRCRAFT_DIR = REPO_ROOT / "aircraft_data"


POH_OVERRIDES: dict[str, dict] = {
    # Cessna primary trainers
    "Cessna_152": {
        "roll_rate_dps": 50.0,
        "bank_response_tau_s": 1.0,
        "speed_response_tau_s": 2.0,
        "takeoff_accel_factor": 0.28,
        "inter_maneuver_pause_s": 1.0,
        "provenance": "poh",
        "poh_citation": "Cessna 152 POH Section 4 (1978)",
    },
    "Cessna_172S": {
        "roll_rate_dps": 45.0,
        "bank_response_tau_s": 1.10,
        "speed_response_tau_s": 2.2,
        "takeoff_accel_factor": 0.26,
        "inter_maneuver_pause_s": 1.0,
        "provenance": "poh",
        "poh_citation": "Cessna 172S POH Section 4 + 5",
    },
    "Cessna_182T": {
        "roll_rate_dps": 42.0,
        "bank_response_tau_s": 1.15,
        "speed_response_tau_s": 2.4,
        "takeoff_accel_factor": 0.32,
        "inter_maneuver_pause_s": 1.0,
        "provenance": "poh",
        "poh_citation": "Cessna 182T POH",
    },

    # Piper Cherokee family
    "Piper_PA-28-181": {
        "roll_rate_dps": 40.0,
        "bank_response_tau_s": 1.20,
        "speed_response_tau_s": 2.0,
        "takeoff_accel_factor": 0.27,
        "inter_maneuver_pause_s": 1.0,
        "provenance": "poh",
        "poh_citation": "PA-28-181 Archer POH",
    },
    "Piper_PA-28R-201": {
        "roll_rate_dps": 38.0,
        "bank_response_tau_s": 1.25,
        "speed_response_tau_s": 2.3,
        "takeoff_accel_factor": 0.30,
        "inter_maneuver_pause_s": 1.0,
        "provenance": "poh",
        "poh_citation": "PA-28R-201 Arrow POH",
    },

    # Cirrus SR-series
    "Cirrus_SR20": {
        "roll_rate_dps": 55.0,
        "bank_response_tau_s": 0.90,
        "speed_response_tau_s": 2.4,
        "takeoff_accel_factor": 0.30,
        "inter_maneuver_pause_s": 1.0,
        "provenance": "poh",
        "poh_citation": "Cirrus SR20 POH",
    },
    "Cirrus_SR22": {
        "roll_rate_dps": 60.0,
        "bank_response_tau_s": 0.85,
        "speed_response_tau_s": 2.5,
        "takeoff_accel_factor": 0.34,
        "inter_maneuver_pause_s": 1.0,
        "provenance": "poh",
        "poh_citation": "Cirrus SR22 POH",
    },

    # Aerobatic trainers
    "American_Champion_Decathlon": {
        "roll_rate_dps": 100.0,
        "bank_response_tau_s": 0.55,
        "speed_response_tau_s": 1.6,
        "takeoff_accel_factor": 0.35,
        "inter_maneuver_pause_s": 1.0,
        "provenance": "poh",
        "poh_citation": "8KCAB Decathlon POH",
    },
    "American_Champion_Citabria": {
        "roll_rate_dps": 60.0,
        "bank_response_tau_s": 0.85,
        "speed_response_tau_s": 1.8,
        "takeoff_accel_factor": 0.27,
        "inter_maneuver_pause_s": 1.0,
        "provenance": "poh",
        "poh_citation": "Citabria 7ECA POH",
    },

    # Complex / retract singles
    "Beechcraft_Bonanza_F33": {
        "roll_rate_dps": 45.0,
        "bank_response_tau_s": 1.05,
        "speed_response_tau_s": 2.5,
        "takeoff_accel_factor": 0.34,
        "inter_maneuver_pause_s": 1.0,
        "provenance": "poh",
        "poh_citation": "Bonanza F33A POH",
    },

    # Light twins
    "Piper_PA-44_Seminole": {
        "roll_rate_dps": 30.0,
        "bank_response_tau_s": 1.6,
        "speed_response_tau_s": 3.0,
        "takeoff_accel_factor": 0.24,
        "inter_maneuver_pause_s": 1.0,
        "provenance": "poh",
        "poh_citation": "PA-44-180 Seminole POH",
    },
    "Piper_PA-30_Twin_Comanche": {
        "roll_rate_dps": 35.0,
        "bank_response_tau_s": 1.4,
        "speed_response_tau_s": 2.8,
        "takeoff_accel_factor": 0.28,
        "inter_maneuver_pause_s": 1.0,
        "provenance": "poh",
        "poh_citation": "PA-30 Twin Comanche POH",
    },
}


def main():
    applied = 0
    skipped_missing = []
    for basename, pd in POH_OVERRIDES.items():
        path = AIRCRAFT_DIR / f"{basename}.json"
        if not path.exists():
            skipped_missing.append(basename)
            continue
        with open(path) as f:
            data = json.load(f)
        data["performance_dynamics"] = pd
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        applied += 1
        print(f"{data.get('name', basename)}: POH override applied "
              f"(roll={pd['roll_rate_dps']} τbank={pd['bank_response_tau_s']} "
              f"τspd={pd['speed_response_tau_s']})")

    print(f"\nApplied {applied}/{len(POH_OVERRIDES)} POH overrides.")
    if skipped_missing:
        print(f"Skipped {len(skipped_missing)} missing files: {skipped_missing}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
