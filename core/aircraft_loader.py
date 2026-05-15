# core/aircraft_loader.py

"""
Aircraft data loading and management.
Handles loading JSON files from the aircraft_data folder and provides
access to the cached data.
"""

import os
import json
import sys
from .logging_setup import get_logger

log = get_logger(__name__)


def dprint(*args, **kwargs):
    """Back-compat shim. Routes to the `tallyaero.em` logger at DEBUG level.

    The original module had ~40 `dprint()` call sites scattered through app.py
    that toggle via `DEBUG_LOG`. Rather than touch every site, we route them
    here. Set `TALLYAERO_LOG=DEBUG` in the environment to see them.
    """
    msg = " ".join(str(a) for a in args)
    log.debug(msg)


def resource_path(filename):
    """Get the absolute path to a resource, works for dev and PyInstaller."""
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, filename)
    return filename


def load_aircraft_data_from_folder(folder_name="aircraft_data"):
    """
    Load all aircraft JSON files from the specified folder.

    Args:
        folder_name: Name of the folder containing aircraft JSON files

    Returns:
        Dict mapping aircraft names to their data
    """
    # Determine the base directory (where this module is located)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    folder_path = os.path.join(base_dir, folder_name)

    aircraft_data = {}

    if not os.path.exists(folder_path):
        log.warning("Aircraft data folder not found: %s", folder_path)
        return aircraft_data

    for filename in os.listdir(folder_path):
        if filename.endswith(".json"):
            filepath = os.path.join(folder_path, filename)
            # Phase 6S: explicit UTF-8 — Windows' default codec (cp1252) chokes
            # on non-ASCII characters in aircraft notes / airport names.
            with open(filepath, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    name = os.path.splitext(filename)[0].replace("_", " ")
                    aircraft_data[name] = data
                except Exception as e:
                    log.error("Failed to load %s: %s", filename, e)

    return aircraft_data


def extract_vmca_value(ac, preferred="clean_up"):
    """
    Extract Vmca value from aircraft data with preference handling.

    Args:
        ac: Aircraft data dict
        preferred: Preferred Vmca configuration ("clean_up", "gear_down", etc.)

    Returns:
        Vmca value or None if not found
    """
    vmca = ac.get("single_engine_limits", {}).get("Vmca", {})
    if isinstance(vmca, dict):
        return vmca.get(preferred) or next(iter(vmca.values()), None)
    return vmca if isinstance(vmca, (int, float)) else None


class DynamicAircraftData:
    """
    Wrapper around the boot-time AIRCRAFT_DATA dict.
    Provides dict-like access without disk I/O on access.
    """
    def __init__(self, data_dict):
        self._data = data_dict

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __contains__(self, key):
        return key in self._data

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def __len__(self):
        return len(self._data)

    def update_aircraft(self, name, data):
        """Update or add aircraft data (for runtime additions)."""
        self._data[name] = data

    def get_raw_dict(self):
        """Get the underlying dict (for dcc.Store)."""
        return self._data


# =============================================================================
# AIRPORT DATA LOADING
# =============================================================================

def load_airport_data(filename="airports/airports.json"):
    """
    Load airport data from JSON file.

    Args:
        filename: Path to airports JSON file

    Returns:
        List of airport dicts with id, name, elevation_ft, lat, lon
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    filepath = os.path.join(base_dir, filename)

    if not os.path.exists(filepath):
        log.warning("Airport data file not found: %s", filepath)
        return []

    try:
        # Phase 6S: explicit UTF-8 for Windows compatibility
        with open(filepath, "r", encoding="utf-8") as f:
            airports = json.load(f)
        return airports
    except Exception as e:
        log.error("Failed to load airports: %s", e)
        return []


def get_airport_options(airports):
    """
    Convert airport list to dropdown options format.

    Label is rich enough that Dash's built-in substring search matches by
    ident, name, city, state/country, and IATA:
        "KAUS — Austin Bergstrom Intl Airport · Austin, TX · 541 ft · IATA AUS"
        "EGLL — London Heathrow Airport · London, GB · 83 ft · IATA LHR"
        "00AA — Aero B Ranch Airport · Cimarron, KS · 3,435 ft"
    """
    options = []
    for ap in airports:
        ident = ap["id"]
        name = ap.get("name") or ""

        # Place: "city, state" for US, "city, country" otherwise. Skip parts
        # that are missing rather than emit lonely commas.
        city = ap.get("municipality")
        state = ap.get("state")             # NASR US only — 2-letter
        country = ap.get("country")         # ISO 2-letter
        if state:
            place = f"{city}, {state}" if city else state
        elif country == "US":
            place = city or ""
        else:
            place = f"{city}, {country}" if city else (country or "")

        elev = ap.get("elevation_ft")
        elev_part = f"{elev:,} ft" if isinstance(elev, (int, float)) else ""

        iata = ap.get("iata")
        iata_part = f"IATA {iata}" if iata and iata != ident else ""

        parts = [f"{ident} — {name}".strip(" —"), place, elev_part, iata_part]
        label = " · ".join(p for p in parts if p)
        options.append({"label": label, "value": ident})
    return options


def get_airport_by_id(airports, airport_id):
    """
    Find airport by ID.

    Args:
        airports: List of airport dicts
        airport_id: Airport identifier (e.g., "KJFK")

    Returns:
        Airport dict or None
    """
    for ap in airports:
        if ap["id"] == airport_id:
            return ap
    return None


# =============================================================================
# DATA INITIALIZATION
# =============================================================================
# Data loading is explicit. `init_data()` is the public API. By default the
# module auto-calls it at import time so existing `from core import AIRCRAFT_DATA`
# patterns continue to work; set `TALLYAERO_NO_AUTO_INIT=1` in the environment
# to skip this (used by tests that want to load a curated subset).
#
# Phase 1 will move the auto-init call out of this module and into app.py.

AIRCRAFT_DATA: dict = {}
AIRPORT_DATA: list = []
AIRPORT_OPTIONS: list = []
aircraft_data = DynamicAircraftData(AIRCRAFT_DATA)


def init_data(
    aircraft_folder: str = "aircraft_data",
    airports_path: str = "airports/airports.json",
) -> tuple[dict, list, list, DynamicAircraftData]:
    """Populate the module-level data caches. Idempotent within a process
    when called with the same args; mutates the globals in place.

    Args:
        aircraft_folder: Path (relative to repo root) for aircraft JSONs.
        airports_path:   Path (relative to repo root) for airports JSON.

    Returns:
        (AIRCRAFT_DATA, AIRPORT_DATA, AIRPORT_OPTIONS, aircraft_data) —
        references to the populated globals, for callers that prefer
        explicit handoffs over module-level imports.
    """
    global AIRCRAFT_DATA, AIRPORT_DATA, AIRPORT_OPTIONS, aircraft_data

    log.info("Loading aircraft data from folder once...")
    new_aircraft = load_aircraft_data_from_folder(aircraft_folder)
    # In-place update so existing `from core import AIRCRAFT_DATA` references
    # still see the new content (rebinding the module global would NOT update
    # already-imported names).
    AIRCRAFT_DATA.clear()
    AIRCRAFT_DATA.update(new_aircraft)
    log.info("Loaded %d aircraft", len(AIRCRAFT_DATA))

    log.info("Loading airport data...")
    new_airports = load_airport_data(airports_path)
    AIRPORT_DATA.clear()
    AIRPORT_DATA.extend(new_airports)
    AIRPORT_OPTIONS.clear()
    AIRPORT_OPTIONS.extend(get_airport_options(AIRPORT_DATA))
    log.info("Loaded %d airports", len(AIRPORT_DATA))

    # `aircraft_data` is a wrapper around AIRCRAFT_DATA; since we mutate
    # in place above, no rebinding needed.
    return AIRCRAFT_DATA, AIRPORT_DATA, AIRPORT_OPTIONS, aircraft_data


# Backward-compat auto-init. Phase 1 makes this explicit from app.py.
if not os.environ.get("TALLYAERO_NO_AUTO_INIT"):
    init_data()
