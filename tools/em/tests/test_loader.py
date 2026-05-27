"""
Verify that data loading is an explicit, idempotent operation — no longer a
module-import side effect.
"""

from __future__ import annotations

import os

import pytest


def test_init_data_idempotent():
    """init_data() can be called repeatedly without leaking state."""
    from core.aircraft_loader import init_data, AIRCRAFT_DATA, AIRPORT_DATA

    n_aircraft_first = len(AIRCRAFT_DATA)
    n_airports_first = len(AIRPORT_DATA)
    assert n_aircraft_first > 0, "auto-init should have populated AIRCRAFT_DATA"

    init_data()

    assert len(AIRCRAFT_DATA) == n_aircraft_first
    assert len(AIRPORT_DATA) == n_airports_first


def test_init_data_returns_references():
    """init_data() returns the same objects it populated."""
    from core.aircraft_loader import init_data, AIRCRAFT_DATA, AIRPORT_DATA

    a, p, opts, wrapper = init_data()
    assert a is AIRCRAFT_DATA
    assert p is AIRPORT_DATA


def test_loader_mutates_in_place_so_existing_imports_see_changes(tmp_path):
    """If a caller has done `from core import AIRCRAFT_DATA` and then init_data
    is re-run with a different folder, the previously-imported reference must
    reflect the new contents — i.e., loader mutates in place rather than rebinding.
    """
    from core.aircraft_loader import init_data, AIRCRAFT_DATA

    # Write a single fake aircraft JSON into a tmp folder, with a name that
    # would be obvious if it leaked into the main run.
    fake = tmp_path / "Tallyaero_TestAircraft.json"
    fake.write_text("""{
  "name": "TallyAero Test Aircraft",
  "type": "single_engine",
  "engine_count": 1,
  "wing_area": 100, "aspect_ratio": 7, "CD0": 0.03, "e": 0.8,
  "configuration_options": {"flaps": ["clean"]},
  "G_limits": {"normal": {"clean": {"positive": 3.8, "negative": -1.5}}, "utility": {"clean": {"positive": 4.4, "negative": -1.5}}, "aerobatic": {"clean": {"positive": 6, "negative": -3}}},
  "stall_speeds": {"clean": {"weights": [1000, 1500], "speeds": [40, 50]}},
  "single_engine_limits": {"best_glide": 60, "best_glide_ratio": 9},
  "engine_options": {"e1": {"horsepower": 100, "power_curve": {"sea_level_max": 100, "derate_per_1000ft": 0.03}}},
  "max_altitude": 12000, "Vne": 150, "Vno": 120, "Vfe": {"landing": 70},
  "CL_max": {"clean": 1.5},
  "arcs": {"white": [40, 70], "green": [45, 120], "yellow": [120, 150], "red": 150},
  "empty_weight": 800, "max_weight": 1500, "seats": 2,
  "cg_range": [15, 25], "fuel_capacity_gal": 20, "fuel_weight_per_gal": 6,
  "prop_thrust_decay": {"T_static_factor": 2.6, "V_max_kts": 150}
}
""")

    init_data(aircraft_folder=str(tmp_path))
    try:
        # Loader uses filename (underscores → spaces) as the key, NOT the
        # JSON `name` field. This is documented behavior — confirmed here.
        assert "Tallyaero TestAircraft" in AIRCRAFT_DATA
        assert len(AIRCRAFT_DATA) == 1
    finally:
        # Restore the production data for any subsequent tests.
        init_data()


def test_no_auto_init_env_var_documented():
    """Sanity check the env-var name we promise as the public escape hatch.

    Tests that want to skip auto-init must set TALLYAERO_NO_AUTO_INIT=1 BEFORE
    importing core. We can't easily simulate that inside a running pytest
    session — but we can at least guard the name from typos.
    """
    # The string must match the one referenced in core/aircraft_loader.py.
    expected = "TALLYAERO_NO_AUTO_INIT"
    src = (
        os.path.join(os.path.dirname(__file__), "..", "core", "aircraft_loader.py")
    )
    with open(src, "r") as fh:
        body = fh.read()
    assert expected in body, (
        f"Env var name '{expected}' not found in aircraft_loader.py — "
        f"either the name has drifted or the auto-init guard is gone."
    )
