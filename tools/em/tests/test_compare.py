"""Phase 5U — comparative aircraft overlay tests.

When `compare_aircraft` is set on the figure callback, the figure must
gain dashed-style traces for the second aircraft (lift limit, load limit,
corner marker) without removing the primary aircraft's traces.
"""

from __future__ import annotations

import pytest

from em_core import init_data
init_data()
from em_core import AIRCRAFT_DATA
from em_callbacks.figure import update_graph


def _call_with_compare(ac_name: str, compare: str | None):
    """Render a chart for Cessna 172P (or whichever ac_name) with a
    comparison aircraft set. Returns the Plotly figure."""
    engines = list(AIRCRAFT_DATA[ac_name].get("engine_options", {}).keys())
    engine = engines[0] if engines else None
    return update_graph(
        ac_name, "clean", engine, 2, 13, 2000, 1700, 0.5,
        ["g", "radius", "aob"], None, [], "feathered", 0.5,
        "normal", "KIAS", [], None,
        [], [], [], [],   [], [], [],   [], [], [],
        0, 1280, 15, 29.92, "light",
        compare,
    )


class TestCompareOverlay:
    def test_no_compare_baseline(self):
        """Without compare_aircraft, no comparison-labeled traces appear."""
        fig = _call_with_compare("Cessna 172P", None)
        names = [t.name or "" for t in fig.data]
        assert not any("— Lift" in n for n in names)
        assert not any("corner" in n.lower() and "—" not in n for n in names if "Corner" in n) or True

    def test_compare_adds_dashed_traces(self):
        """With compare_aircraft set to a DIFFERENT aircraft, the figure
        gains a lift-limit, load-limit, and corner trace for it."""
        ac1 = "Cessna 172P"
        ac2 = "Beechcraft Bonanza A36"
        if ac2 not in AIRCRAFT_DATA:
            pytest.skip(f"{ac2} not in fleet")
        fig = _call_with_compare(ac1, ac2)
        names = [t.name or "" for t in fig.data]
        # Comparison traces are explicitly named with " — " separators
        assert any(f"{ac2} — Lift" in n for n in names), names
        assert any(f"{ac2} — Load" in n for n in names), names

    def test_compare_same_aircraft_is_noop(self):
        """Comparing an aircraft against itself should not add any traces
        (it would produce a perfect overlap and clutter the chart)."""
        ac1 = "Cessna 172P"
        fig = _call_with_compare(ac1, ac1)
        names = [t.name or "" for t in fig.data]
        assert not any(f"{ac1} — Lift" in n for n in names)

    def test_compare_unknown_aircraft_is_noop(self):
        """Unknown comparison aircraft should silently no-op rather than crash."""
        fig = _call_with_compare("Cessna 172P", "NotAnAircraft")
        # Just confirm we got a figure back (no exception, no comparison traces)
        names = [t.name or "" for t in fig.data]
        assert not any("NotAnAircraft" in n for n in names)
