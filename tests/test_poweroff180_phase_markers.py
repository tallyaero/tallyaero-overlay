"""Tests for the PO180 phase-transition helper (ACS Gap 5).

The Power-Off 180 sim emits hover entries tagged with segment in
{downwind, turn, final, touchdown}. The helper walks the list and
returns (index, segment) tuples for each transition — the callback
uses these to drop CircleMarkers on the map at the abeam / 90° / 45° /
final boundaries so the pilot can read the geometry at a glance.
"""
from __future__ import annotations

from callbacks.maneuvers.poweroff180 import _phase_transition_indices


def _hover(*runs):
    """Helper: build a hover list from (segment, count) runs."""
    out = []
    for seg, n in runs:
        out.extend([{"segment": seg}] * n)
    return out


def test_simple_three_segment_pattern():
    hover = _hover(("downwind", 30), ("base", 20), ("final", 50))
    assert _phase_transition_indices(hover) == [
        (0, "downwind"),
        (30, "base"),
        (50, "final"),
    ]


def test_includes_initial_segment_at_index_zero():
    hover = _hover(("downwind", 5))
    assert _phase_transition_indices(hover) == [(0, "downwind")]


def test_empty_hover_returns_empty():
    assert _phase_transition_indices([]) == []


def test_no_segment_change_one_entry():
    hover = _hover(("downwind", 100))
    assert _phase_transition_indices(hover) == [(0, "downwind")]


def test_handles_missing_segment_field():
    """Entries without a segment field are skipped (no transition)."""
    hover = [{"alt": 1000}, {"segment": "downwind"}, {"segment": "downwind"}]
    out = _phase_transition_indices(hover)
    # The "downwind" at index 1 counts as the first segment seen.
    assert out == [(1, "downwind")]


def test_actual_po180_segments():
    """Matches the real PO180 sim sequence."""
    hover = _hover(("downwind", 25), ("turn", 30), ("final", 40), ("touchdown", 1))
    assert _phase_transition_indices(hover) == [
        (0, "downwind"),
        (25, "turn"),
        (55, "final"),
        (95, "touchdown"),
    ]
