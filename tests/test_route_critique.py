"""Tests for core.route_critique — survivability score math."""
from __future__ import annotations

import pytest

from core.route_critique import score_route


# === Band boundaries ========================================================

def test_clean_flat_route_is_excellent():
    """Calm-day flatland flight with full divert coverage → 95+."""
    c = score_route(
        n_samples=50,
        n_terrain_conflict_samples=0,
        n_no_divert_samples=0,
        longest_no_divert_nm=0.0,
        pct_landable_slope=98.0,
        pct_corridor_suitable_land=0.85,
        min_agl_ft=4500.0,
    )
    assert c.band == "excellent"
    assert c.score >= 95


def test_mountain_crossing_is_marginal_or_critical():
    """A high-density terrain conflict route gets penalized hard."""
    c = score_route(
        n_samples=50,
        n_terrain_conflict_samples=15,   # 30% of route below ridge
        n_no_divert_samples=30,           # 60% no divert
        longest_no_divert_nm=42.0,        # ~32 NM excess past 10 NM threshold
        pct_landable_slope=22.0,          # mostly steep
        pct_corridor_suitable_land=0.05,
        min_agl_ft=200.0,
    )
    assert c.band in ("marginal", "critical")
    assert c.score < 50


def test_overwater_no_land_in_glide_is_critical():
    """Cessna over open ocean — no land at all."""
    c = score_route(
        n_samples=40,
        n_terrain_conflict_samples=0,
        n_no_divert_samples=40,           # 100% no divert
        longest_no_divert_nm=180.0,
        pct_landable_slope=None,          # toggle off
        pct_corridor_suitable_land=0.0,
        min_agl_ft=5500.0,
    )
    # 100% no-divert + huge longest stretch should drop hard.
    assert c.band in ("critical", "marginal")
    assert c.score <= 50


# === Factor ordering ========================================================

def test_factors_sorted_by_severity():
    """The worst penalty should be the first factor returned."""
    c = score_route(
        n_samples=20,
        n_terrain_conflict_samples=10,    # -17.5 pts
        n_no_divert_samples=2,            # -2.5 pts
        longest_no_divert_nm=11.0,        # -0.6 pts
        pct_landable_slope=80.0,          # -3 pts
        pct_corridor_suitable_land=0.5,   # -5 pts
        min_agl_ft=1500.0,
    )
    assert c.factors[0].label == "Terrain conflict"
    # Each subsequent factor should be less painful (greater or equal points)
    for i in range(len(c.factors) - 1):
        assert c.factors[i].points <= c.factors[i + 1].points


# === Bonus path =============================================================

def test_high_agl_grants_bonus():
    base = score_route(
        n_samples=20,
        n_terrain_conflict_samples=0,
        n_no_divert_samples=0,
        longest_no_divert_nm=0.0,
        pct_landable_slope=100.0,
        pct_corridor_suitable_land=1.0,
        min_agl_ft=500.0,
    )
    with_bonus = score_route(
        n_samples=20,
        n_terrain_conflict_samples=0,
        n_no_divert_samples=0,
        longest_no_divert_nm=0.0,
        pct_landable_slope=100.0,
        pct_corridor_suitable_land=1.0,
        min_agl_ft=3000.0,
    )
    # Both should be 100 (clamped), but the bonus path should explicitly
    # include the bonus factor.
    labels = [f.label for f in with_bonus.factors]
    assert "Comfortable AGL clearance" in labels
    labels_base = [f.label for f in base.factors]
    assert "Comfortable AGL clearance" not in labels_base


# === Clamping ===============================================================

def test_score_clamped_to_zero():
    """Even a route with every penalty maxed out doesn't go negative."""
    c = score_route(
        n_samples=10,
        n_terrain_conflict_samples=10,
        n_no_divert_samples=10,
        longest_no_divert_nm=500.0,
        pct_landable_slope=0.0,
        pct_corridor_suitable_land=0.0,
        min_agl_ft=0.0,
    )
    assert c.score == 0
    assert c.band == "critical"


def test_score_clamped_to_hundred():
    """The bonus path can't push above 100."""
    c = score_route(
        n_samples=10,
        n_terrain_conflict_samples=0,
        n_no_divert_samples=0,
        longest_no_divert_nm=0.0,
        pct_landable_slope=100.0,
        pct_corridor_suitable_land=1.0,
        min_agl_ft=10000.0,
    )
    assert c.score == 100


# === Optional inputs ========================================================

def test_handles_no_slope_data():
    """When the Slope toggle is off, the slope factor is skipped
    entirely (not zeroed)."""
    c = score_route(
        n_samples=10,
        n_terrain_conflict_samples=0,
        n_no_divert_samples=0,
        longest_no_divert_nm=0.0,
        pct_landable_slope=None,
        pct_corridor_suitable_land=None,
        min_agl_ft=1500.0,
    )
    labels = {f.label for f in c.factors}
    assert "Steep terrain in corridor" not in labels
    assert "Little suitable land" not in labels


# === Color/band consistency =================================================

def test_color_hex_per_band():
    c = score_route(
        n_samples=10, n_terrain_conflict_samples=0,
        n_no_divert_samples=0, longest_no_divert_nm=0.0,
        pct_landable_slope=100.0, pct_corridor_suitable_land=1.0,
        min_agl_ft=3000.0,
    )
    assert c.color_hex().startswith("#")
    assert len(c.color_hex()) == 7
