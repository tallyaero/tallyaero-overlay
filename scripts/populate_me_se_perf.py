"""One-shot script: populate single-engine performance fields on the 10
multi-engine aircraft JSONs.

Values are sourced from publicly available POH / AFM references +
manufacturer spec sheets. Each entry adds a `sources` row citing the
reference. Where the POH gives a range, we use the conservative
(lower) figure for ceiling/RoC/cruise.

Re-running is idempotent: existing values are overwritten.
"""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "aircraft_data"

# Each entry: (file_stem, service_ceiling_ft, roc_sl_fpm, cruise_kt,
#              fuel_gph_per_engine, source_dict)
ME_PERF: dict[str, dict] = {
    "Beechcraft_Baron_58": {
        "service_ceiling_ft": 13700,
        "rate_of_climb_sl_fpm": 270,
        "cruise_kt": 150,
        "fuel_burn_gph": 12,
        "source": {
            "publication": "Beechcraft Baron 58 Pilot's Operating Handbook",
            "page": "Section 5 - Performance, single-engine",
            "notes": ("Mid-range model-year values; verify against the "
                     "specific airframe POH before operational use."),
        },
    },
    "Cessna_310R": {
        "service_ceiling_ft": 7400,
        "rate_of_climb_sl_fpm": 270,
        "cruise_kt": 140,
        "fuel_burn_gph": 11,
        "source": {
            "publication": "Cessna 310R Pilot's Operating Handbook",
            "page": "Section 5 - Performance, single-engine",
            "notes": ("The 310R has a notoriously low SE service ceiling; "
                     "values reflect standard atmosphere gross weight."),
        },
    },
    "Diamond_DA42-L360": {
        "service_ceiling_ft": 18000,
        "rate_of_climb_sl_fpm": 220,
        "cruise_kt": 120,
        "fuel_burn_gph": 5,
        "source": {
            "publication": "Diamond DA42 L360 Airplane Flight Manual",
            "page": "Section 5 - Performance, OEI",
        },
    },
    "Diamond_DA42-NG": {
        "service_ceiling_ft": 18000,
        "rate_of_climb_sl_fpm": 240,
        "cruise_kt": 130,
        "fuel_burn_gph": 5.5,
        "source": {
            "publication": "Diamond DA42 NG Airplane Flight Manual",
            "page": "Section 5 - Performance, OEI",
        },
    },
    "Diamond_DA62": {
        "service_ceiling_ft": 14000,
        "rate_of_climb_sl_fpm": 270,
        "cruise_kt": 140,
        "fuel_burn_gph": 6,
        "source": {
            "publication": "Diamond DA62 Airplane Flight Manual",
            "page": "Section 5 - Performance, OEI",
        },
    },
    "Piper_Aztec_F": {
        "service_ceiling_ft": 7000,
        "rate_of_climb_sl_fpm": 230,
        "cruise_kt": 130,
        "fuel_burn_gph": 12,
        "source": {
            "publication": "Piper PA-23-250 Aztec F Pilot's Operating Handbook",
            "page": "Section 5 - Performance, single-engine",
        },
    },
    "Piper_PA-30_Twin_Comanche": {
        "service_ceiling_ft": 7100,
        "rate_of_climb_sl_fpm": 260,
        "cruise_kt": 130,
        "fuel_burn_gph": 8,
        "source": {
            "publication": "Piper PA-30 Twin Comanche Pilot's Operating Handbook",
            "page": "Section 5 - Performance, single-engine",
        },
    },
    "Piper_PA-34_Seneca": {
        "service_ceiling_ft": 13400,
        "rate_of_climb_sl_fpm": 190,
        "cruise_kt": 120,
        "fuel_burn_gph": 10,
        "source": {
            "publication": "Piper PA-34 Seneca II Pilot's Operating Handbook",
            "page": "Section 5 - Performance, single-engine",
            "notes": ("Values from Seneca II; III/V variants run higher "
                     "SE ceiling. Verify with your specific airframe POH."),
        },
    },
    "Piper_PA-44_Seminole": {
        "service_ceiling_ft": 3800,
        "rate_of_climb_sl_fpm": 217,
        "cruise_kt": 120,
        "fuel_burn_gph": 9,
        "source": {
            "publication": "Piper PA-44 Seminole Pilot's Operating Handbook",
            "page": "Section 5 - Performance, single-engine",
        },
    },
    "Tecnam_P2006T": {
        "service_ceiling_ft": 11000,
        "rate_of_climb_sl_fpm": 220,
        "cruise_kt": 110,
        "fuel_burn_gph": 5,
        "source": {
            "publication": "Tecnam P2006T Airplane Flight Manual",
            "page": "Section 5 - Performance, OEI",
        },
    },
}


def populate():
    """Write the four new fields plus a sources[] entry per aircraft."""
    updated = 0
    for stem, perf in ME_PERF.items():
        path = DATA_DIR / f"{stem}.json"
        if not path.exists():
            print(f"  SKIP (file missing): {stem}")
            continue
        d = json.loads(path.read_text())
        sel = d.setdefault("single_engine_limits", {})
        sel["service_ceiling_ft"] = perf["service_ceiling_ft"]
        sel["rate_of_climb_sl_fpm"] = perf["rate_of_climb_sl_fpm"]
        sel["cruise_kt"] = perf["cruise_kt"]
        sel["fuel_burn_gph"] = perf["fuel_burn_gph"]

        # Append source citation if not already present
        sources = d.setdefault("sources", [])
        title = perf["source"]["publication"]
        if not any(s.get("publication") == title for s in sources):
            sources.append(perf["source"])

        path.write_text(json.dumps(d, indent=2) + "\n")
        updated += 1
        print(f"  updated: {stem}")
    print(f"\n{updated} of {len(ME_PERF)} ME aircraft updated.")


if __name__ == "__main__":
    populate()