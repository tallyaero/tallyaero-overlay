#!/usr/bin/env python3
"""
Merge OurAirports runway data into existing airports.json

This script:
1. Loads the existing airports.json (preserving all existing fields)
2. Parses OurAirports runways.csv
3. Adds runway data to matching airports
4. Saves the updated airports.json

Runway data structure added:
{
    "runways": [
        {"id": "17", "heading": 170, "length_ft": 5500},
        {"id": "35", "heading": 350, "length_ft": 5500}
    ]
}
"""

import csv
import json
import os
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
AIRPORTS_JSON = PROJECT_DIR / "airports" / "airports.json"
OURAIRPORTS_RUNWAYS = Path("/tmp/ourairports_runways.csv")


def load_existing_airports():
    """Load existing airports.json"""
    with open(AIRPORTS_JSON, "r") as f:
        return json.load(f)


def parse_runways_csv():
    """
    Parse OurAirports runways.csv and return dict of airport_ident -> list of runways

    Each runway has two ends (le = low end, he = high end).
    We create two runway entries (one for each direction).
    """
    runways_by_airport = {}

    with open(OURAIRPORTS_RUNWAYS, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            airport_ident = row["airport_ident"]

            # Skip closed runways
            if row.get("closed") == "1":
                continue

            # Get runway length
            try:
                length_ft = int(float(row["length_ft"])) if row["length_ft"] else None
            except (ValueError, TypeError):
                length_ft = None

            if length_ft is None or length_ft < 100:  # Skip invalid/very short runways
                continue

            runways = []

            # Low end runway
            le_ident = row.get("le_ident", "").strip()
            le_heading = row.get("le_heading_degT", "").strip()
            if le_ident:
                try:
                    heading = int(round(float(le_heading))) if le_heading else None
                    # Normalize heading to 1-360
                    if heading is not None:
                        heading = heading % 360
                        if heading == 0:
                            heading = 360
                    runways.append({
                        "id": le_ident,
                        "heading": heading,
                        "length_ft": length_ft
                    })
                except (ValueError, TypeError):
                    # If no heading, try to derive from runway number
                    if le_ident.isdigit() or (len(le_ident) <= 3 and le_ident[:-1].isdigit()):
                        rwy_num = int(le_ident.rstrip("LRC"))
                        heading = rwy_num * 10
                        if heading == 0:
                            heading = 360
                        runways.append({
                            "id": le_ident,
                            "heading": heading,
                            "length_ft": length_ft
                        })

            # High end runway
            he_ident = row.get("he_ident", "").strip()
            he_heading = row.get("he_heading_degT", "").strip()
            if he_ident:
                try:
                    heading = int(round(float(he_heading))) if he_heading else None
                    # Normalize heading to 1-360
                    if heading is not None:
                        heading = heading % 360
                        if heading == 0:
                            heading = 360
                    runways.append({
                        "id": he_ident,
                        "heading": heading,
                        "length_ft": length_ft
                    })
                except (ValueError, TypeError):
                    # If no heading, try to derive from runway number
                    if he_ident.isdigit() or (len(he_ident) <= 3 and he_ident[:-1].isdigit()):
                        rwy_num = int(he_ident.rstrip("LRC"))
                        heading = rwy_num * 10
                        if heading == 0:
                            heading = 360
                        runways.append({
                            "id": he_ident,
                            "heading": heading,
                            "length_ft": length_ft
                        })

            # Add to airport's runway list
            if runways:
                if airport_ident not in runways_by_airport:
                    runways_by_airport[airport_ident] = []
                runways_by_airport[airport_ident].extend(runways)

    return runways_by_airport


def fill_reciprocal_headings(runways):
    """
    Fill in missing headings by calculating reciprocal from paired runway.
    E.g., if runway 09 has heading 90, then runway 27 should have heading 270.
    """
    # Build dict of runway id -> runway data
    by_id = {r["id"]: r for r in runways}

    for rwy in runways:
        if rwy.get("heading") is not None:
            continue

        # Try to find reciprocal runway
        rwy_id = rwy["id"]

        # Get numeric part of runway ID
        num_part = rwy_id.rstrip("LRCNSEW")
        suffix = rwy_id[len(num_part):] if len(num_part) < len(rwy_id) else ""

        if num_part.isdigit():
            rwy_num = int(num_part)
            # Calculate reciprocal runway number
            recip_num = (rwy_num + 18) % 36
            if recip_num == 0:
                recip_num = 36

            # Handle L/R/C suffixes
            recip_suffix = ""
            if suffix == "L":
                recip_suffix = "R"
            elif suffix == "R":
                recip_suffix = "L"
            elif suffix == "C":
                recip_suffix = "C"
            elif suffix in ["N", "S", "E", "W"]:
                # Cardinal direction runways - opposite direction
                opposites = {"N": "S", "S": "N", "E": "W", "W": "E"}
                recip_suffix = opposites.get(suffix, "")

            recip_id = f"{recip_num:02d}{recip_suffix}"

            # Look for reciprocal in our runway list
            if recip_id in by_id and by_id[recip_id].get("heading") is not None:
                recip_heading = by_id[recip_id]["heading"]
                # Calculate our heading as reciprocal
                new_heading = (recip_heading + 180) % 360
                if new_heading == 0:
                    new_heading = 360
                rwy["heading"] = new_heading
            else:
                # Fall back to deriving from runway number
                heading = rwy_num * 10
                if heading == 0:
                    heading = 360
                rwy["heading"] = heading

    return runways


def merge_runway_data(airports, runways_by_airport):
    """
    Merge runway data into airports list.
    Preserves all existing fields, only adds 'runways' where data exists.
    """
    airports_updated = 0
    runways_added = 0

    for airport in airports:
        airport_id = airport.get("id", "")

        # Try direct match
        if airport_id in runways_by_airport:
            runways = runways_by_airport[airport_id]
        # Try with K prefix (for US airports)
        elif f"K{airport_id}" in runways_by_airport:
            runways = runways_by_airport[f"K{airport_id}"]
        else:
            continue

        # Remove duplicates (same runway ID)
        seen_ids = set()
        unique_runways = []
        for rwy in runways:
            if rwy["id"] not in seen_ids:
                seen_ids.add(rwy["id"])
                unique_runways.append(rwy)

        # Fill in missing reciprocal headings
        unique_runways = fill_reciprocal_headings(unique_runways)

        # Sort by runway ID
        unique_runways.sort(key=lambda r: r["id"])

        if unique_runways:
            airport["runways"] = unique_runways
            airports_updated += 1
            runways_added += len(unique_runways)

    return airports, airports_updated, runways_added


def save_airports(airports):
    """Save airports back to JSON with nice formatting"""
    with open(AIRPORTS_JSON, "w") as f:
        json.dump(airports, f, indent=2)


def main():
    print("Loading existing airports.json...")
    airports = load_existing_airports()
    print(f"  Found {len(airports)} airports")

    print("\nParsing OurAirports runways.csv...")
    runways_by_airport = parse_runways_csv()
    print(f"  Found runways for {len(runways_by_airport)} airports")

    print("\nMerging runway data...")
    airports, updated, runways_added = merge_runway_data(airports, runways_by_airport)
    print(f"  Updated {updated} airports with {runways_added} total runways")

    print("\nSaving updated airports.json...")
    save_airports(airports)
    print("  Done!")

    # Show sample
    print("\nSample airport with runway data:")
    for airport in airports:
        if "runways" in airport and len(airport.get("runways", [])) >= 2:
            print(json.dumps(airport, indent=2))
            break


if __name__ == "__main__":
    main()
