#!/usr/bin/env python3
"""
Add Vx and Vy climb speeds to aircraft JSON files.

IMPORTANT: This script only ADDS new fields (Vx, Vy).
It does NOT modify or remove any existing fields to ensure backward compatibility.

Data sources: POH documents, Quizlet flashcards, aviation forums, manufacturer specs
"""

import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
AIRCRAFT_DIR = PROJECT_DIR / "aircraft_data"

# Make the repo root importable so we can use core.log from this CLI script.
sys.path.insert(0, str(PROJECT_DIR))
from core.log import get_logger  # noqa: E402

log = get_logger(__name__)

# Vx/Vy data from research (KIAS)
# Format: "filename": {"Vx": value, "Vy": value}
# None means data not found/not applicable
CLIMB_DATA = {
    # === CESSNA ===
    "Cessna_150.json": {"Vx": 54, "Vy": 67},
    "Cessna_152.json": {"Vx": 55, "Vy": 67},
    "Cessna_162.json": {"Vx": 55, "Vy": 69},  # Skycatcher
    "Cessna_172M.json": {"Vx": 60, "Vy": 73},
    "Cessna_172N.json": {"Vx": 60, "Vy": 73},
    "Cessna_172P.json": {"Vx": 60, "Vy": 74},
    "Cessna_172R.json": {"Vx": 62, "Vy": 74},
    "Cessna_172S.json": {"Vx": 62, "Vy": 74},
    "Cessna_177.json": {"Vx": 62, "Vy": 76},  # Cardinal 150hp
    "Cessna_177RG.json": {"Vx": 67, "Vy": 84},  # Cardinal RG 200hp
    "Cessna_182P.json": {"Vx": 59, "Vy": 80},
    "Cessna_182Q.json": {"Vx": 59, "Vy": 80},
    "Cessna_182T.json": {"Vx": 60, "Vy": 80},
    "Cessna_206.json": {"Vx": 69, "Vy": 89},  # Stationair
    "Cessna_210.json": {"Vx": 68, "Vy": 96},  # Centurion
    "Cessna_310R.json": {"Vx": 85, "Vy": 107},  # Twin

    # === PIPER ===
    "Piper_PA-28-140.json": {"Vx": 64, "Vy": 74},  # Cherokee 140
    "Piper_PA-28-151.json": {"Vx": 64, "Vy": 75},  # Warrior I
    "Piper_PA-28-161.json": {"Vx": 63, "Vy": 79},  # Warrior II/III
    "Piper_PA-28-181.json": {"Vx": 64, "Vy": 76},  # Archer
    "Piper_PA-28R-200.json": {"Vx": 72, "Vy": 89},  # Arrow 200
    "Piper_PA-28R-201.json": {"Vx": 72, "Vy": 90},  # Arrow III
    "Piper_PA-28R-201T.json": {"Vx": 72, "Vy": 90},  # Turbo Arrow
    "Piper_PA-28RT-201.json": {"Vx": 72, "Vy": 90},  # Arrow IV
    "Piper_PA-32-260.json": {"Vx": 67, "Vy": 87},  # Cherokee Six
    "Piper_PA-32R-300.json": {"Vx": 72, "Vy": 94},  # Lance/Saratoga
    "Piper_PA-30_Twin_Comanche.json": {"Vx": 90, "Vy": 112},
    "Piper_PA-34_Seneca.json": {"Vx": 80, "Vy": 89},
    "Piper_PA-34_Seneca 2.json": {"Vx": 80, "Vy": 89},
    "Piper_PA-44_Seminole.json": {"Vx": 82, "Vy": 88},
    "Piper_Aztec_F.json": {"Vx": 90, "Vy": 105},

    # === CIRRUS ===
    "Cirrus_SR20.json": {"Vx": 81, "Vy": 96},
    "Cirrus_SR22.json": {"Vx": 78, "Vy": 101},
    "Cirrus_SR22T.json": {"Vx": 80, "Vy": 103},

    # === DIAMOND ===
    "Diamond_DA20-A1.json": {"Vx": 60, "Vy": 75},
    "Diamond_DA20-C1.json": {"Vx": 60, "Vy": 75},
    "Diamond_DA20-C1 2.json": {"Vx": 60, "Vy": 75},
    "Diamond_DA40-180.json": {"Vx": 66, "Vy": 73},
    "Diamond_DA40-NG.json": {"Vx": 66, "Vy": 76},
    "Diamond_DA42-L360.json": {"Vx": 78, "Vy": 85},
    "Diamond_DA42-NG.json": {"Vx": 78, "Vy": 85},
    "Diamond_DA62.json": {"Vx": 82, "Vy": 89},

    # === MOONEY ===
    "Mooney_M20C.json": {"Vx": 78, "Vy": 90},  # Mark 21
    "Mooney_M20E.json": {"Vx": 80, "Vy": 92},  # Super 21
    "Mooney_M20J.json": {"Vx": 79, "Vy": 96},  # 201
    "Mooney_M20R.json": {"Vx": 80, "Vy": 105},  # Ovation

    # === BEECHCRAFT ===
    "Beechcraft_Bonanza_A36.json": {"Vx": 80, "Vy": 95},
    "Beechcraft_Bonanza_F33.json": {"Vx": 78, "Vy": 92},
    "Beechcraft_Musketeer.json": {"Vx": 65, "Vy": 80},
    "Beechcraft_Sierra.json": {"Vx": 68, "Vy": 84},
    "Beechcraft_Sundowner.json": {"Vx": 65, "Vy": 80},
    "Beechcraft_Baron_58.json": {"Vx": 84, "Vy": 100},

    # === GRUMMAN/AMERICAN GENERAL ===
    "Grumman_AA-5.json": {"Vx": 67, "Vy": 82},  # Traveler
    "Grumman_AA-5B.json": {"Vx": 70, "Vy": 85},  # Tiger

    # === SOCATA/DAHER ===
    "Socata_TB9.json": {"Vx": 65, "Vy": 80},  # Tampico
    "Socata_TB10.json": {"Vx": 68, "Vy": 84},  # Tobago
    "Socata_TB20.json": {"Vx": 75, "Vy": 95},  # Trinidad

    # === TECNAM ===
    "Tecnam_P2002.json": {"Vx": 56, "Vy": 68},
    "Tecnam_P2006T.json": {"Vx": 74, "Vy": 82},

    # === PIPISTREL ===
    "Pipistrel_Alpha_Trainer.json": {"Vx": 52, "Vy": 62},
    "Pipistrel_Virus.json": {"Vx": 58, "Vy": 70},

    # === ROBIN ===
    "Robin_DR400.json": {"Vx": 65, "Vy": 78},
    "Robin_R3000.json": {"Vx": 68, "Vy": 82},

    # === AMERICAN CHAMPION ===
    "American_Champion_Citabria.json": {"Vx": 55, "Vy": 70},
    "American_Champion_Decathlon.json": {"Vx": 58, "Vy": 72},
    "American_Champion_Scout.json": {"Vx": 52, "Vy": 65},

    # === AERONCA ===
    "Aeronca_Champ.json": {"Vx": 48, "Vy": 60},
    "Aeronca_Chief.json": {"Vx": 48, "Vy": 60},
    "Champion_7EC.json": {"Vx": 52, "Vy": 65},

    # === BELLANCA ===
    "Bellanca_Super_Viking.json": {"Vx": 78, "Vy": 95},

    # === MAULE ===
    "Maule_M-7.json": {"Vx": 52, "Vy": 68},

    # === AVIAT ===
    "Aviat Husky A-1C.json": {"Vx": 52, "Vy": 68},

    # === TAYLORCRAFT ===
    "Taylorcraft_BC-12D.json": {"Vx": 48, "Vy": 60},

    # === LUSCOMBE ===
    "Luscombe_8A.json": {"Vx": 52, "Vy": 65},

    # === STINSON ===
    "Stinson_108.json": {"Vx": 55, "Vy": 70},

    # === ERCOUPE ===
    "Ercoupe_415C.json": {"Vx": 55, "Vy": 68},

    # === VAN'S RV SERIES ===
    "Van's_RV-6.json": {"Vx": 70, "Vy": 90},
    "Van's_RV-8.json": {"Vx": 75, "Vy": 95},
    "Van's_RV-9A.json": {"Vx": 65, "Vy": 85},
    "Van's_RV-10.json": {"Vx": 80, "Vy": 100},
    "Van's_RV-12.json": {"Vx": 55, "Vy": 70},
    "Van's_RV-14A.json": {"Vx": 75, "Vy": 95},

    # === FLIGHT DESIGN ===
    "Flight_Design_CTLS.json": {"Vx": 52, "Vy": 65},

    # === REMOS ===
    "Remos_GX.json": {"Vx": 50, "Vy": 62},

    # === EVEKTOR ===
    "Evektor_SportStar.json": {"Vx": 52, "Vy": 65},

    # === ZLIN ===
    "Zlin_Savage.json": {"Vx": 42, "Vy": 55},
    "Zlin_Z-242L.json": {"Vx": 62, "Vy": 78},

    # === GAME BIRD ===
    "GameBird_GB1.json": {"Vx": 70, "Vy": 90},

    # === AEROBATIC AIRCRAFT ===
    "Extra_300.json": {"Vx": 75, "Vy": 95},
    "Extra_300L.json": {"Vx": 75, "Vy": 95},
    "Extra_330SC.json": {"Vx": 80, "Vy": 100},
    "Extra_NG.json": {"Vx": 80, "Vy": 100},
    "CAP_232.json": {"Vx": 78, "Vy": 95},
    "MX_Aircraft_MXS.json": {"Vx": 80, "Vy": 100},
    "Pitts_S-1C.json": {"Vx": 65, "Vy": 80},
    "Pitts_S-1C-TB.json": {"Vx": 65, "Vy": 80},
    "Pitts_S-2C.json": {"Vx": 72, "Vy": 88},
    "Sukhoi_Su-26.json": {"Vx": 85, "Vy": 105},
    "Zivko_Edge_540.json": {"Vx": 85, "Vy": 105},

    # === MILITARY TRAINERS ===
    "PT-17_Stearman.json": {"Vx": 58, "Vy": 72},
    "T-6A_Texan_II.json": {"Vx": 100, "Vy": 130},
    "T-6B_Texan_II.json": {"Vx": 100, "Vy": 130},

    # === WARBIRDS (approximate based on published data) ===
    "North_American_P51-D_Mustang.json": {"Vx": 120, "Vy": 160},
    "Supermarine_Spitfire.json": {"Vx": 115, "Vy": 155},
    "Messerschmitt Bf 109G-6.json": {"Vx": 118, "Vy": 158},
    "Focke-Wulf_FW_190_A-8.json": {"Vx": 125, "Vy": 165},
    "Vought_F4U-4_Corsair.json": {"Vx": 120, "Vy": 160},
    "Grumman_F6F-5_Hellcat.json": {"Vx": 110, "Vy": 150},
    "Grumman_F8F-2_Bearcat.json": {"Vx": 115, "Vy": 155},
    "Mitsubishi_A6M5_Zero.json": {"Vx": 95, "Vy": 130},
    "Kawanishi_N1K2-J_Shiden-Kai.json": {"Vx": 115, "Vy": 155},
    "Yakovlev_Yak-3.json": {"Vx": 110, "Vy": 150},
}


def update_aircraft_json(filepath, vx, vy):
    """
    Add Vx and Vy to aircraft JSON file.
    Only adds new fields - does NOT modify existing data.
    """
    with open(filepath, 'r') as f:
        data = json.load(f)

    # Store original keys to verify we don't lose anything
    original_keys = set(data.keys())

    # Only add if not already present
    modified = False
    if 'Vx' not in data and vx is not None:
        data['Vx'] = vx
        modified = True
    if 'Vy' not in data and vy is not None:
        data['Vy'] = vy
        modified = True

    # Verify all original keys still exist (backward compatibility check)
    for key in original_keys:
        if key not in data:
            raise ValueError(f"CRITICAL: Lost key '{key}' in {filepath}")

    if modified:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

    return modified


def main():
    log.info("Adding Vx/Vy climb speeds to aircraft JSON files...")
    log.info("=" * 60)

    updated = 0
    skipped = 0
    not_found = []

    for filename in sorted(os.listdir(AIRCRAFT_DIR)):
        if not filename.endswith('.json'):
            continue

        filepath = AIRCRAFT_DIR / filename

        if filename in CLIMB_DATA:
            vx = CLIMB_DATA[filename].get("Vx")
            vy = CLIMB_DATA[filename].get("Vy")

            if update_aircraft_json(filepath, vx, vy):
                log.info(f"  Updated: {filename} (Vx={vx}, Vy={vy})")
                updated += 1
            else:
                log.info(f"  Skipped: {filename} (already has Vx/Vy)")
                skipped += 1
        else:
            not_found.append(filename)

    log.info("=" * 60)
    log.info(f"Updated: {updated} aircraft")
    log.info(f"Skipped: {skipped} aircraft (already had data)")

    if not_found:
        log.info(f"Aircraft without Vx/Vy data ({len(not_found)}):")
        for f in not_found:
            log.info(f"  - {f}")


if __name__ == "__main__":
    main()
