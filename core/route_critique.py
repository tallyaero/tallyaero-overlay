"""Route survivability score — aggregate the engine-out signals into
one 0-100 number so the pilot reads a single verdict instead of
five separate stats.

The score is deliberately pessimistic by construction (starts at
100, every concern subtracts), so the question becomes "what's
costing me points?" rather than "is this enough?". The factor list
returned alongside the score makes the deductions transparent.

Inputs come from the existing route compute pipeline:
  - corridor terrain conflicts (samples below ridge)
  - airport-reach divert coverage
  - slope-landable percentage of the corridor
  - suitable-land coverage of the corridor

Categorical bands:
  Excellent ≥ 85   pilot has obvious outs everywhere
  Good 60-84       workable but not painless
  Marginal 30-59   long stretches of risk
  Critical < 30    if the engine quits here you may not survive

The thresholds are calibrated against representative US flights I
flew through the system during development — a calm-day flatland
hop scores 95+, a mountain crossing scores 35-50, a Cessna over
open ocean with no land in glide scores ≤ 20.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CritiqueFactor:
    """One contribution to the survivability score."""
    label: str            # short human label, e.g. "Terrain conflict"
    points: float         # signed; negative = penalty, positive = bonus
    detail: str           # one-line "why" — surfaces in the UI


@dataclass
class RouteCritique:
    """Aggregate survivability verdict for one route."""
    score: int                          # 0-100, clamped
    band: str                           # "excellent" / "good" / "marginal" / "critical"
    headline: str                       # e.g. "Marginal — long no-divert stretch"
    factors: list[CritiqueFactor]       # ordered most-impactful first

    def color_hex(self) -> str:
        return {
            "excellent": "#15803d",     # Tailwind green-700
            "good":      "#65a30d",     # lime-600
            "marginal":  "#d97706",     # amber-600
            "critical":  "#b91c1c",     # red-700
        }.get(self.band, "#6b7280")


def _band_for(score: int) -> str:
    if score >= 85:
        return "excellent"
    if score >= 60:
        return "good"
    if score >= 30:
        return "marginal"
    return "critical"


def _headline_for(band: str, factors: list[CritiqueFactor]) -> str:
    band_label = {
        "excellent": "Excellent",
        "good":      "Good",
        "marginal":  "Marginal",
        "critical":  "Critical",
    }[band]
    if band == "excellent":
        return f"{band_label} — clear outs throughout"
    # Find the most-painful factor (lowest signed points) to name in the headline.
    penalties = [f for f in factors if f.points < 0]
    if not penalties:
        return band_label
    worst = min(penalties, key=lambda f: f.points)
    return f"{band_label} — {worst.label.lower()}"


def score_route(
    n_samples: int,
    n_terrain_conflict_samples: int,
    n_no_divert_samples: int,
    longest_no_divert_nm: float,
    pct_landable_slope: float | None,
    pct_corridor_suitable_land: float | None,
    min_agl_ft: float,
) -> RouteCritique:
    """Compute the survivability critique from the per-route metrics.

    Args:
        n_samples: total route samples
        n_terrain_conflict_samples: samples where cruise alt < ridge
        n_no_divert_samples: samples with NO airfield in glide
        longest_no_divert_nm: longest contiguous run with no divert
        pct_landable_slope: 0-100, % of corridor pixels at or below
            the slope threshold (None if Slope map was off)
        pct_corridor_suitable_land: 0-1, fraction of the corridor
            covered by OSM suitable-land polygons (None if Suitable
            Land was off)
        min_agl_ft: minimum AGL the route ever sees

    Returns:
        RouteCritique with score, band, headline, and the ordered
        factor list.
    """
    factors: list[CritiqueFactor] = []
    score = 100.0

    n = max(1, int(n_samples))

    # --- Terrain conflict — biggest single penalty ---
    f_terrain = float(n_terrain_conflict_samples) / n
    if f_terrain > 0:
        p = -35.0 * f_terrain
        factors.append(CritiqueFactor(
            label="Terrain conflict",
            points=p,
            detail=(f"{n_terrain_conflict_samples} of {n} samples below "
                    f"ridge ({f_terrain * 100:.0f}% of route)"),
        ))
        score += p

    # --- No-divert coverage ---
    f_no_div = float(n_no_divert_samples) / n
    if f_no_div > 0:
        p = -25.0 * f_no_div
        factors.append(CritiqueFactor(
            label="No airfield in glide",
            points=p,
            detail=(f"{n_no_divert_samples} of {n} samples ({f_no_div * 100:.0f}% "
                    "of route) can't reach any airport engine-out"),
        ))
        score += p

    # --- Longest no-divert stretch ---
    if longest_no_divert_nm > 10.0:
        excess = longest_no_divert_nm - 10.0
        p = -0.6 * excess
        factors.append(CritiqueFactor(
            label="Long no-divert stretch",
            points=p,
            detail=(f"{longest_no_divert_nm:.0f} NM contiguous without an "
                    f"airfield in glide"),
        ))
        score += p

    # --- Slope unlandability ---
    if pct_landable_slope is not None:
        unlandable_frac = max(0.0, 1.0 - pct_landable_slope / 100.0)
        if unlandable_frac > 0:
            p = -15.0 * unlandable_frac
            factors.append(CritiqueFactor(
                label="Steep terrain in corridor",
                points=p,
                detail=(f"{unlandable_frac * 100:.0f}% of corridor pixels "
                        "above the slope threshold"),
            ))
            score += p

    # --- Suitable-land coverage ---
    if pct_corridor_suitable_land is not None:
        suitable_frac = max(0.0, min(1.0, pct_corridor_suitable_land))
        deficit = 1.0 - suitable_frac
        if deficit > 0:
            p = -10.0 * deficit
            factors.append(CritiqueFactor(
                label="Little suitable land",
                points=p,
                detail=(f"{suitable_frac * 100:.0f}% of the corridor is "
                        "OSM-tagged as viable land"),
            ))
            score += p

    # --- AGL clearance bonus ---
    if min_agl_ft >= 2000.0:
        p = 5.0
        factors.append(CritiqueFactor(
            label="Comfortable AGL clearance",
            points=p,
            detail=f"Min AGL {min_agl_ft:.0f} ft — plenty of glide energy",
        ))
        score += p

    # Order factors by impact magnitude, most painful first.
    factors.sort(key=lambda f: f.points)

    clamped = int(round(max(0.0, min(100.0, score))))
    band = _band_for(clamped)
    headline = _headline_for(band, factors)
    return RouteCritique(
        score=clamped, band=band, headline=headline, factors=factors,
    )
