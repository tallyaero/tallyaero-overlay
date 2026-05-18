"""Runtime three-tier loader for aircraft performance_dynamics.

Maneuver simulators call `dynamics_for(ac)` and get back a dict with
the six required fields regardless of how much per-aircraft data the
JSON file carries. The three tiers (in order of preference):

    poh           — hand-curated, written by scripts/apply_poh_dynamics.py.
                    Most reliable. Preserved verbatim.
    class_derived — computed offline by scripts/classify_dynamics.py and
                    written into the JSON. Preserved verbatim.
    estimated     — computed on the fly here, used when the aircraft has
                    no performance_dynamics block at all. The provenance
                    is stamped "estimated" so downstream UI can mark
                    these as runtime-derived rather than data-tier-2.

A final hard-coded fallback handles the edge case where on-the-fly
derivation itself fails (missing G_limits / engine_options / etc.). The
fallback values are generic light-single defaults — never matches a
specific airframe, but keeps the sim from crashing.
"""
from __future__ import annotations

import copy
from typing import Any

from scripts.classify_dynamics import derive_dynamics


_FALLBACK_DYNAMICS: dict[str, Any] = {
    "roll_rate_dps": 40.0,
    "bank_response_tau_s": 1.86,
    "speed_response_tau_s": 2.0,
    "takeoff_accel_factor": 0.28,
    "inter_maneuver_pause_s": 1.0,
    "provenance": "estimated",
    "poh_citation": None,
}


def dynamics_for(ac: dict[str, Any]) -> dict[str, Any]:
    """Return a complete performance_dynamics dict for `ac`.

    Never mutates the input. The returned dict is a fresh copy that
    callers may freely modify."""
    pd = ac.get("performance_dynamics")
    if isinstance(pd, dict) and pd.get("roll_rate_dps"):
        return copy.deepcopy(pd)

    try:
        derived = derive_dynamics(ac)
        derived["provenance"] = "estimated"
        return derived
    except Exception:
        return copy.deepcopy(_FALLBACK_DYNAMICS)
