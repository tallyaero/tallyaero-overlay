"""Phase 1 wind-correctness tests for impossible_turn.

Two things were broken before:
  1. When a wind_profile was supplied (any time after picking an airport),
     the sim silently clobbered the user's env-wind-dir / env-wind-speed
     with the column's mid-altitude wind.
  2. A single mid-altitude wind was used for every phase — takeoff
     ground roll included — instead of an altitude-varying lookup.

These tests pin the post-fix contract:
  - User surface wind always wins for the surface (ground roll, near-TD).
  - When a wind_profile is provided, climb + glide use per-altitude
    samples from the column (with the SFC layer overridden to honor
    the user's surface wind).
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from geopy.point import Point as GeoPoint

from core.winds_aloft import WindProfile
from simulation.impossible_turn import (
    simulate_impossible_turn,
    simulate_climb_phase,
)


AIRCRAFT_DIR = Path(__file__).resolve().parent.parent / "aircraft_data"


@pytest.fixture(scope="module")
def cessna_172s() -> dict:
    return json.loads((AIRCRAFT_DIR / "Cessna_172S.json").read_text())


@pytest.fixture(scope="module")
def c172_engine(cessna_172s) -> str:
    return next(iter(cessna_172s["engine_options"].keys()))


def _common_kwargs(ac, engine):
    return dict(
        start_point=GeoPoint(30.5, -97.5),
        runway_heading_deg=270.0,
        turn_dir="left",
        reaction_sec=3.0,
        start_ias_kias=75.0,
        altitude_agl=1000.0,
        ac=ac,
        engine_option=engine,
        weight_lbs=2300.0,
        oat_c=15.0,
        altimeter_inhg=29.92,
        find_min_alt=False,
    )


def test_with_surface_override_replaces_sfc_layer():
    """SFC layer is replaced; higher layers untouched; interpolation
    transitions smoothly from override to next layer."""
    prof = WindProfile([(0, 270, 5), (1500, 250, 20), (3000, 240, 30)])
    new = prof.with_surface_override(90.0, 25.0, surface_alt_ft_msl=0.0)
    layers = new.layers()
    assert layers[0] == (0.0, 90.0, 25.0)
    assert layers[1] == (1500.0, 250.0, 20.0)
    assert layers[2] == (3000.0, 240.0, 30.0)
    # Surface lookup returns the override exactly.
    assert new.at(0.0) == (90.0, 25.0)
    # Mid-altitude is between override and next layer.
    mid = new.at(750.0)
    assert 5.0 < mid[1] < 25.0  # speed interpolates between 25 and 20


def test_user_wind_is_not_clobbered_when_profile_is_present(cessna_172s, c172_engine):
    """The critical regression: with a wind_profile present, the sim
    used to overwrite the user's wind_dir/wind_speed with a mid-altitude
    sample. After the fix, the user's surface wind is honored even when
    a profile is supplied — the profile only drives shear above SFC.

    We verify this by running two sims with the same wind_profile but
    radically different user surface winds. The paths must differ.
    """
    prof = WindProfile([(0, 270, 5), (1500, 250, 20), (3000, 240, 30)])

    kw = _common_kwargs(cessna_172s, c172_engine)
    _, _, meta_calm = simulate_impossible_turn(
        wind_dir=270.0, wind_speed=0.0, wind_profile=prof, **kw,
    )
    _, _, meta_strong = simulate_impossible_turn(
        wind_dir=90.0, wind_speed=25.0, wind_profile=prof, **kw,
    )

    # Different surface winds → different final cross-track / impact.
    # If the sim were still clobbering with the profile mean, both
    # runs would produce identical metadata.
    assert meta_calm.get("final_xtrack_ft") != meta_strong.get("final_xtrack_ft"), \
        "User wind override appears to be ignored: meta is identical across very different surface winds"


def test_climb_phase_per_altitude_wind_when_profile_supplied(cessna_172s, c172_engine):
    """The climb phase should use per-tick wind from the profile, so the
    crab angle (wca) entries in the hover log must change with altitude
    under a sheared column. Without profile, wca is constant per altitude
    because wind is constant."""
    # Strong shear in direction (220 at SFC → 020 at 3000): WCA will
    # change sign through the climb if per-tick lookup is working.
    sheared = WindProfile([(0, 220, 15), (1500, 100, 15), (3000, 20, 15)])

    failure_pt, _hdg, _t, _path, hover = simulate_climb_phase(
        start_point={"lat": 30.5, "lon": -97.5},
        heading_deg=0.0,                # climbing north
        start_alt_agl=0.0,
        target_alt_agl=2000.0,          # well above 1500 ft layer boundary
        ac=cessna_172s,
        weight_lbs=2300.0,
        oat_c=15.0,
        altimeter_inhg=29.92,
        field_elev_ft=500.0,            # so MSL ranges 500..2500
        wind_dir=220.0,
        wind_speed=15.0,
        timestep_sec=0.5,
        engine_option=c172_engine,
        wind_profile=sheared,
    )
    wcas = [h["wca"] for h in hover if h.get("wca") is not None]
    assert len(wcas) > 5
    # With shear, the WCA range across the climb should be non-trivial
    # (early ticks fight a different crosswind than late ticks).
    wca_range = max(wcas) - min(wcas)
    assert wca_range > 1.0, (
        f"Per-altitude wind sampling not influencing crab — WCA range {wca_range:.2f}° "
        f"under strong shear column. Expected > 1°."
    )


def test_no_profile_falls_back_to_static_wind(cessna_172s, c172_engine):
    """No wind_profile → sim uses the user-supplied wind_dir/wind_speed
    as a static value (the legacy single-wind path stays working)."""
    kw = _common_kwargs(cessna_172s, c172_engine)
    p, h, m = simulate_impossible_turn(
        wind_dir=270.0, wind_speed=15.0, **kw,
    )
    # Should produce a runnable path and meta dict, no crash.
    assert isinstance(m, dict)
    assert "success" in m
    assert len(p) > 5
