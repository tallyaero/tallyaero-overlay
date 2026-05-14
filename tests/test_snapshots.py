"""Snapshot tests for canonical maneuver outputs.

These lock the simulation engine's outputs for a fixed scenario set.
Deliberate physics changes regenerate snapshots via:

    venv/bin/pytest tests/test_snapshots.py --snapshot-update

Any other snapshot drift is a bug.

Signatures here mirror what tests/test_physics.py adopted after probing
the real simulation module APIs — the plan's idealized kwargs do not
match the production code. See test_physics.py for the full notes."""

import json
from pathlib import Path

from geopy import Point as GeoPoint


REPO_ROOT = Path(__file__).resolve().parent.parent
_AIRCRAFT_PATH = REPO_ROOT / "aircraft_data" / "Cessna_172P.json"


def _load_cessna_172p() -> dict:
    """Load the curated Cessna 172P aircraft dict for tests that need ac."""
    with open(_AIRCRAFT_PATH) as f:
        return json.load(f)


# -------------------------------------------------------------------
# Helper — strip floating-point noise to make snapshots stable across
# numpy versions, machine precision, etc.
# -------------------------------------------------------------------

def _round_hover(hover: list[dict], digits: int = 1) -> list[dict]:
    """Round all float values in the hover list to `digits` decimal places."""
    def r(v):
        if isinstance(v, float):
            return round(v, digits)
        return v
    return [{k: r(v) for k, v in pt.items()} for pt in hover]


# -------------------------------------------------------------------
# Snapshots
# -------------------------------------------------------------------

def test_engine_out_glide_kaus_5000ft_calm(snapshot):
    """Engine-out glide from 5,000 ft AGL near KAUS, calm wind, Cessna 172P,
    Lycoming O-320-D2J, windmilling prop. Touchdown target ~5 NM east —
    well within glide range so the path is produced cleanly."""
    from simulation.engine_out import simulate_engineout_glide

    ac = _load_cessna_172p()
    path, hover, meta = simulate_engineout_glide(
        start_point=GeoPoint(30.5, -97.5),
        start_heading=90.0,
        touchdown_point=GeoPoint(30.5, -97.42),
        touchdown_heading=270.0,
        ac=ac,
        engine_option="Lycoming O-320-D2J",
        weight_lbs=2300.0,
        flap_config="clean",
        prop_config="windmilling",
        oat_c=15.0,
        altimeter_inhg=29.92,
        wind_dir=0.0,
        wind_speed=0.0,
        altitude_agl=5000.0,
    )
    assert len(path) > 5, f"path empty/short ({len(path)}) — bad scenario"
    assert _round_hover(hover[:3]) == snapshot(name="hover_start")
    assert _round_hover(hover[-3:]) == snapshot(name="hover_end")
    assert len(path) == snapshot(name="path_length")


def test_steep_turn_left_45deg_110kt(snapshot):
    """Steep turn, 45° bank left, 110 KIAS, 3,000 ft, calm wind. Note:
    simulate_steep_turn returns a 2-tuple (path, hover) — not 3-tuple."""
    from simulation.steep_turn import simulate_steep_turn

    path, hover = simulate_steep_turn(
        entry_point={"lat": 30.5, "lon": -97.5},
        entry_heading_deg=270.0,
        altitude_ft=3000.0,
        bank_angle_deg=45.0,
        turn_sequence="left",
        ias_knots=110.0,
        oat_c=15.0,
        wind_dir_deg=0.0,
        wind_speed_kt=0.0,
    )
    assert len(path) > 10, f"path too short ({len(path)}) — bad scenario"
    assert _round_hover(hover[:3]) == snapshot(name="hover_start")
    assert _round_hover(hover[-3:]) == snapshot(name="hover_end")
    assert len(path) == snapshot(name="path_length")


def test_impossible_turn_1000ft_45deg(snapshot):
    """Impossible turn (engine failure on takeoff), 1,000 ft AGL start,
    Cessna 172P, 65 KIAS, 4 s reaction, left turn, calm wind. find_min_alt
    disabled to skip the binary search and keep the snapshot deterministic."""
    from simulation.impossible_turn import simulate_impossible_turn

    ac = _load_cessna_172p()
    path, hover, meta = simulate_impossible_turn(
        start_point=GeoPoint(30.5, -97.5),
        runway_heading_deg=270.0,
        turn_dir="left",
        reaction_sec=4.0,
        start_ias_kias=65.0,
        altitude_agl=1000.0,
        ac=ac,
        engine_option="Lycoming O-320-D2J",
        weight_lbs=2300.0,
        oat_c=15.0,
        altimeter_inhg=29.92,
        wind_dir=0.0,
        wind_speed=0.0,
        find_min_alt=False,
    )
    assert len(path) > 5, f"path too short ({len(path)}) — bad scenario"
    assert _round_hover(hover[:3]) == snapshot(name="hover_start")
    assert _round_hover(hover[-3:]) == snapshot(name="hover_end")
    assert len(path) == snapshot(name="path_length")
