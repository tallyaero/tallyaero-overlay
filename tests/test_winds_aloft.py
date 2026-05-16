"""Tests for core.winds_aloft. Network mocked; no live API hits."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core import winds_aloft as wa


# === Standard atmosphere ====================================================

def test_altitude_to_hpa_sea_level():
    assert abs(wa.altitude_ft_to_hpa(0) - 1013.25) < 0.5


def test_altitude_to_hpa_5500_ft():
    """5500 ft ≈ 830 hPa (between 850 and 800 hPa available levels)."""
    p = wa.altitude_ft_to_hpa(5500)
    assert 820 < p < 845


def test_altitude_to_hpa_10000_ft():
    p = wa.altitude_ft_to_hpa(10000)
    assert 690 < p < 710


def test_altitude_to_hpa_monotonic():
    """Higher altitude → lower pressure."""
    prev = wa.altitude_ft_to_hpa(0)
    for ft in (1000, 3000, 5000, 10000, 18000, 30000, 39000):
        p = wa.altitude_ft_to_hpa(ft)
        assert p < prev
        prev = p


# === Bracketing levels ======================================================

def test_levels_at_sea_level():
    assert wa.open_meteo_levels_for(1013) == (1000, 1000)


def test_levels_at_5500_ft_pressure():
    """~830 hPa sits between 850 and 800."""
    lo, hi = wa.open_meteo_levels_for(830)
    assert lo == 850
    assert hi == 800


def test_levels_at_high_altitude():
    """At an exact available level (200), bracketing is
    (200, next-lower-pressure) which interpolates correctly via frac=0."""
    lo, hi = wa.open_meteo_levels_for(200)
    assert lo == 200
    # Either (200, 200) if we treated exact-match as endpoint, or
    # (200, 150) — both are correct because interp_wind handles
    # frac=0 and returns wind_lo.
    assert hi in (200, 150)


def test_levels_above_top():
    """Pressure below 100 hPa (above ~53000 ft) clamps to 100."""
    lo, hi = wa.open_meteo_levels_for(50)
    assert lo == hi == 100


# === Wind interpolation =====================================================

def test_interp_wind_same_level():
    """If lo == hi, returns the low value unchanged."""
    result = wa.interp_wind(850, 850, 850, (270.0, 20.0), (270.0, 20.0))
    assert result == (270.0, 20.0)


def test_interp_wind_exact_low_level():
    """At the lower-altitude level, returns wind_low."""
    result = wa.interp_wind(850, 850, 800, (270.0, 20.0), (290.0, 25.0))
    assert abs(result[0] - 270.0) < 1.0
    assert abs(result[1] - 20.0) < 1.0


def test_interp_wind_exact_high_level():
    result = wa.interp_wind(800, 850, 800, (270.0, 20.0), (290.0, 25.0))
    assert abs(result[0] - 290.0) < 1.0
    assert abs(result[1] - 25.0) < 1.0


def test_interp_wind_wraparound_zero_crossing():
    """350° and 10° at adjacent levels should blend to ~0°, not 180°."""
    result = wa.interp_wind(825, 850, 800, (350.0, 20.0), (10.0, 20.0))
    # Midpoint should be near 0° (or 360°)
    blended = result[0]
    diff = min(abs(blended - 0.0), abs(blended - 360.0))
    assert diff < 5.0, f"got {blended}° expected ~0°"
    assert abs(result[1] - 20.0) < 1.0


def test_interp_wind_speed_increases_midpoint():
    """Linear-in-vector means midpoint of (270, 20) and (270, 30) →
    (270, 25)."""
    result = wa.interp_wind(825, 850, 800, (270.0, 20.0), (270.0, 30.0))
    assert abs(result[0] - 270.0) < 1.0
    assert abs(result[1] - 25.0) < 0.5


# === Vector conversion (round-trip sanity) =================================

def test_uv_round_trip_north():
    """Wind FROM 360° (north wind) at 20 kt round-trips."""
    u, v = wa._uv_from_dir_speed(360.0, 20.0)
    d, s = wa._dir_speed_from_uv(u, v)
    # 360° normalizes to 0°
    assert abs((d % 360.0) - 0.0) < 0.01
    assert abs(s - 20.0) < 0.01


def test_uv_round_trip_west():
    u, v = wa._uv_from_dir_speed(270.0, 30.0)
    d, s = wa._dir_speed_from_uv(u, v)
    assert abs(d - 270.0) < 0.01
    assert abs(s - 30.0) < 0.01


# === HTTP fetch (mocked) ====================================================

def _make_response(payload):
    m = MagicMock()
    m.json.return_value = payload
    m.raise_for_status = MagicMock()
    return m


@pytest.fixture(autouse=True)
def clear_wind_cache():
    wa.clear_cache()
    yield
    wa.clear_cache()


def test_fetch_winds_happy_path():
    """Mock a single-location Open-Meteo response."""
    payload = [{
        "hourly": {
            "time": ["2026-05-16T15:00", "2026-05-16T16:00"],
            "wind_speed_850hPa": [12.0, 14.0],
            "wind_direction_850hPa": [220.0, 230.0],
            "wind_speed_800hPa": [15.0, 17.0],
            "wind_direction_800hPa": [225.0, 235.0],
        }
    }]
    forecast_time = datetime(2026, 5, 16, 15, 0, tzinfo=timezone.utc)
    with patch.object(wa.requests, "get", return_value=_make_response(payload)):
        out = wa.fetch_winds_aloft(
            [(33.0635, -80.2795)], [5500.0], forecast_hour_utc=forecast_time)
    assert out is not None
    assert len(out) == 1
    dir_deg, speed_kt = out[0]
    # 5500 ft ≈ 830 hPa, between 850 and 800 — interpolated
    assert 10.0 < speed_kt < 18.0
    assert 215.0 < dir_deg < 240.0


def test_fetch_winds_http_failure_returns_none():
    """Network errors -> None."""
    import requests as _r
    with patch.object(wa.requests, "get",
                      side_effect=_r.ConnectionError("network down")):
        out = wa.fetch_winds_aloft(
            [(33.0, -80.0)], [5500.0],
            forecast_hour_utc=datetime(2026, 5, 16, 15, 0, tzinfo=timezone.utc))
    assert out is None


def test_fetch_winds_empty_input_returns_none():
    assert wa.fetch_winds_aloft([], []) is None


def test_fetch_winds_length_mismatch_returns_none():
    assert wa.fetch_winds_aloft([(33.0, -80.0)], [5500.0, 6500.0]) is None


def test_fetch_winds_malformed_response_returns_none():
    """Bad JSON shape -> None."""
    payload = [{"hourly": {}}]   # missing time + speed/dir lists
    with patch.object(wa.requests, "get", return_value=_make_response(payload)):
        out = wa.fetch_winds_aloft(
            [(33.0, -80.0)], [5500.0],
            forecast_hour_utc=datetime(2026, 5, 16, 15, 0, tzinfo=timezone.utc))
    assert out is None


def test_fetch_winds_multi_location_batch():
    """Two locations batched in one call."""
    payload = [
        {
            "hourly": {
                "time": ["2026-05-16T15:00"],
                "wind_speed_850hPa": [10.0],
                "wind_direction_850hPa": [200.0],
                "wind_speed_800hPa": [12.0],
                "wind_direction_800hPa": [210.0],
            }
        },
        {
            "hourly": {
                "time": ["2026-05-16T15:00"],
                "wind_speed_850hPa": [18.0],
                "wind_direction_850hPa": [240.0],
                "wind_speed_800hPa": [20.0],
                "wind_direction_800hPa": [245.0],
            }
        },
    ]
    forecast_time = datetime(2026, 5, 16, 15, 0, tzinfo=timezone.utc)
    with patch.object(wa.requests, "get", return_value=_make_response(payload)) as mock_get:
        out = wa.fetch_winds_aloft(
            [(33.0635, -80.2795), (32.1276, -81.2021)],
            [5500.0, 5500.0],
            forecast_hour_utc=forecast_time)
    assert out is not None
    assert len(out) == 2
    # First location should reflect ~210° / 11 kt, second ~242° / 19 kt
    assert 190 < out[0][0] < 220 and 8 < out[0][1] < 14
    assert 230 < out[1][0] < 250 and 16 < out[1][1] < 22
    # One HTTP call (batched)
    assert mock_get.call_count == 1


def test_fetch_winds_cache_hit_no_second_call():
    """Re-calling with same args within the same hour hits the LRU."""
    payload = [{
        "hourly": {
            "time": ["2026-05-16T15:00"],
            "wind_speed_850hPa": [10.0],
            "wind_direction_850hPa": [200.0],
            "wind_speed_800hPa": [12.0],
            "wind_direction_800hPa": [210.0],
        }
    }]
    forecast_time = datetime(2026, 5, 16, 15, 0, tzinfo=timezone.utc)
    with patch.object(wa.requests, "get",
                      return_value=_make_response(payload)) as mock_get:
        out1 = wa.fetch_winds_aloft(
            [(33.0635, -80.2795)], [5500.0], forecast_hour_utc=forecast_time)
        out2 = wa.fetch_winds_aloft(
            [(33.0635, -80.2795)], [5500.0], forecast_hour_utc=forecast_time)
    assert out1 == out2
    assert mock_get.call_count == 1   # second call was cached
