"""
Data loading utilities for aircraft and airport data.
Consolidated from app.py and edit_aircraft_page.py (deduplicated).
"""
import os
import json


def load_aircraft_data(folder=None):
    """
    Load all aircraft data from JSON files.

    Args:
        folder: Path to aircraft_data folder. If None, uses default location.

    Returns:
        Dictionary mapping aircraft names to their data dicts
    """
    if folder is None:
        base = os.path.dirname(os.path.dirname(__file__))
        folder = os.path.join(base, "data", "aircraft_data")

        # Fallback to root location if data hasn't been moved yet
        if not os.path.exists(folder):
            folder = os.path.join(base, "aircraft_data")

    data = {}
    if os.path.exists(folder):
        for filename in os.listdir(folder):
            if filename.endswith(".json"):
                with open(os.path.join(folder, filename)) as f:
                    name = filename.replace(".json", "")
                    data[name] = json.load(f)
    return data


def load_airport_data():
    """
    Load airport data from JSON file.

    Returns:
        List of airport dictionaries with keys: id, name, lat, lon, elevation_ft
    """
    base = os.path.dirname(os.path.dirname(__file__))

    # Try new location first
    path = os.path.join(base, "data", "airports", "airports.json")

    # Fallback to root location if data hasn't been moved yet
    if not os.path.exists(path):
        path = os.path.join(base, "airports", "airports.json")

    with open(path, "r") as f:
        return json.load(f)


# Cached singletons for performance
_aircraft_data = None
_airport_data = None
_available_aircraft = None


def get_aircraft_data():
    """Get cached aircraft data."""
    global _aircraft_data, _available_aircraft
    if _aircraft_data is None:
        _aircraft_data = load_aircraft_data()
        _available_aircraft = sorted(_aircraft_data.keys())
    return _aircraft_data


def get_available_aircraft():
    """Get sorted list of available aircraft names."""
    global _available_aircraft
    if _available_aircraft is None:
        get_aircraft_data()
    return _available_aircraft


def get_airport_data():
    """Get cached airport data."""
    global _airport_data
    if _airport_data is None:
        _airport_data = load_airport_data()
    return _airport_data
