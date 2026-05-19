"""Phase H2 · WindProfile (column with in-memory interpolation).

The `wind_column_at_point` HTTP path is exercised by the existing
`tests/test_winds_aloft*.py` (it uses fetch_winds_aloft under the hood);
here we test the in-memory interpolant behavior, store round-trip,
and METAR SFC override.
"""
from core.winds_aloft import WindProfile, wind_column_at_point
import core.winds_aloft as wa


def test_clamps_below_floor():
    p = WindProfile([(1500, 270, 10), (6000, 290, 30)])
    d, k = p.at(0)
    assert d == 270 and k == 10


def test_clamps_above_ceiling():
    p = WindProfile([(0, 270, 10), (3000, 280, 20)])
    d, k = p.at(9000)
    assert d == 280 and k == 20


def test_linear_interp_speed():
    p = WindProfile([(0, 270, 10), (6000, 270, 30)])
    _, k = p.at(3000)
    assert abs(k - 20) < 1e-6


def test_circular_interp_direction_wraps():
    """350° → 010° must blend through 0°, not through 180°."""
    p = WindProfile([(0, 350, 20), (6000, 10, 20)])
    d, _ = p.at(3000)
    # Acceptable wrap: 0° (i.e., the midpoint should be ~360 or ~0).
    assert d > 355 or d < 5


def test_empty_layers_returns_zero():
    p = WindProfile([])
    assert p.at(3000) == (0.0, 0.0)


def test_store_round_trip():
    p = WindProfile([(0, 270, 10), (3000, 280, 20)])
    rehydrated = WindProfile.from_store(p.to_store())
    assert rehydrated is not None
    assert rehydrated.at(1500) == p.at(1500)


def test_from_store_handles_none():
    assert WindProfile.from_store(None) is None
    assert WindProfile.from_store({}) is None
    assert WindProfile.from_store({"layers": []}) is None


def test_column_uses_metar_for_surface(monkeypatch):
    """If METAR provides SFC wind, it OVERRIDES the model's 0-ft layer."""
    # 6-layer alt array → 6 fetched tuples (all set to model 250/15).
    model_resp = [(250.0, 15.0)] * 6
    monkeypatch.setattr(wa, "fetch_winds_aloft", lambda *a, **k: model_resp)

    metar = {"wind_dir_deg": 180, "wind_speed_kt": 8}
    prof = wind_column_at_point(33.06, -80.28, surface_metar=metar)
    assert prof is not None
    d, k = prof.at(0)
    assert d == 180.0 and k == 8.0
    # Layer above SFC stays at the model value.
    d2, k2 = prof.at(3000)
    assert d2 == 250.0 and k2 == 15.0


def test_column_returns_none_when_model_fails(monkeypatch):
    monkeypatch.setattr(wa, "fetch_winds_aloft", lambda *a, **k: None)
    assert wind_column_at_point(33.06, -80.28) is None
