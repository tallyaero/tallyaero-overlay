"""Phase 4 stall-margin gate for impossible_turn bank search.

The pre-Phase-4 bank search could return any bank in [bank_min, 45°]
without checking whether the airframe could fly at best-glide IAS
while at that bank. For a 172S at gross in landing flaps, the search
might recommend ~40° bank → required IAS = Vs × √n ≈ 60 kt, while
best-glide is 65 kt; only a 5 kt margin. With small headwind or pilot
error, that's a stall in the turn — the classic impossible-turn killer.

Phase 4 adds a stall-margin gate: banks whose Vs×√n would put best-
glide IAS within 5 kt of stall are rejected upfront. Meta carries the
margin at the recommended bank and the lowest bank the gate rejected
so the UI can show "stall capped at N°".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from simulation.impossible_turn import simulate_impossible_turn


AIRCRAFT_DIR = Path(__file__).resolve().parent.parent / "aircraft_data"


def _sim(ac_name: str, flap_config: str = "clean") -> dict:
    ac = json.loads((AIRCRAFT_DIR / f"{ac_name}.json").read_text())
    engine = next(iter(ac["engine_options"].keys()))
    _path, _hover, meta = simulate_impossible_turn(
        start_point=None,
        runway_heading_deg=270.0,
        turn_dir="left",
        reaction_sec=3.0,
        start_ias_kias=0.0,
        altitude_agl=1000.0,
        ac=ac,
        engine_option=engine,
        weight_lbs=float(ac["max_weight"]),
        oat_c=15.0,
        altimeter_inhg=29.92,
        wind_dir=270.0,
        wind_speed=10.0,
        find_min_alt=False,
        flap_config=flap_config,
        include_takeoff_climb=True,
        threshold_point={"lat": 30.5, "lon": -97.5},
        runway_length_ft=5000.0,
    )
    return meta


def test_meta_carries_stall_margin():
    """Every run should report `stall_margin_kt` so the result panel
    can color-code it (red < 4 kt, amber < 8 kt, green ≥ 8 kt)."""
    meta = _sim("Cessna_172S")
    assert isinstance(meta.get("stall_margin_kt"), (int, float))
    assert isinstance(meta.get("stall_speed_at_bank_kt"), (int, float))


def test_clean_172s_has_healthy_margin():
    """C172S clean at gross, ~15-30° bank should be nowhere near stall."""
    meta = _sim("Cessna_172S", flap_config="clean")
    margin = float(meta.get("stall_margin_kt", 0))
    assert margin > 8.0, f"C172S clean stall margin {margin:.1f} kt suspiciously thin"


def test_landing_flaps_compress_margin_or_cap_bank():
    """With landing flaps, stall speed is lower BUT the bank ceiling
    can still cap because best-glide IAS may be lower too. The gate
    should either reduce the margin from clean OR record a capped bank."""
    clean = _sim("Cessna_172S", flap_config="clean")
    landing = _sim("Cessna_172S", flap_config="landing")
    # Either margin must differ between configs, or cap engaged.
    different_margin = abs(float(clean.get("stall_margin_kt", 0))
                           - float(landing.get("stall_margin_kt", 0))) > 0.5
    capped = landing.get("stall_capped_bank_deg") is not None
    assert different_margin or capped, (
        "Stall gate not differentiating clean vs landing flap config"
    )


def test_gate_never_returns_unsafe_bank():
    """The recommended bank's Vs×√n must always be at least
    STALL_MARGIN_KT below best-glide IAS. No exceptions — that's the
    contract of the gate."""
    import math
    from simulation.base import _get_best_glide_and_ratio
    from simulation.impossible_turn import _get_stall_speed

    ac = json.loads((AIRCRAFT_DIR / "Cessna_172S.json").read_text())
    engine = next(iter(ac["engine_options"].keys()))
    meta = _sim("Cessna_172S")
    best_glide_kt, _ = _get_best_glide_and_ratio(ac, engine, "clean", "windmilling")
    bank = float(meta.get("bank_deg", 0))
    vs = _get_stall_speed(ac, float(ac["max_weight"]), "clean")
    cos_b = math.cos(math.radians(min(bank, 89.9)))
    n = 1 / cos_b
    vs_at_n = vs * math.sqrt(n)
    assert best_glide_kt - vs_at_n >= 4.0, (
        f"Recommended bank {bank:.1f}° puts Vs×√n at {vs_at_n:.1f} kt with "
        f"best-glide {best_glide_kt:.1f} kt — gate failed its contract"
    )
