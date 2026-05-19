"""Phase H1 · NOAA AWC METAR fetcher + parse + cache.

Tests don't hit the network — we monkeypatch _http_get.
"""
from unittest.mock import patch
import core.metar as metar_mod
from core.metar import fetch_metar, parse_metar_json


_SAMPLE_KDYB = {
    "icaoId": "KDYB",
    "obsTime": "2026-05-19T13:55:00Z",
    "wdir": 250,
    "wspd": 12,
    "wgst": 18,
    "temp": 22.0,
    "dewp": 18.0,
    # AWC returns altim in hPa (hectopascals) even for US stations.
    # 1018 hPa ≈ 30.05 inHg; the parser converts when value > 100.
    "altim": 1017.95,
    "rawOb": "KDYB 191355Z 25012G18KT 10SM SCT040 22/18 A3005",
}


def setup_function(_fn):
    metar_mod._CACHE.clear()


def test_parse_picks_newest_record():
    older = dict(_SAMPLE_KDYB, obsTime="2026-05-19T12:55:00Z", wdir=240)
    newer = dict(_SAMPLE_KDYB, obsTime="2026-05-19T13:55:00Z", wdir=250)
    out = parse_metar_json([older, newer])
    assert out["wind_dir_deg"] == 250


def test_parse_carries_fields():
    out = parse_metar_json([_SAMPLE_KDYB])
    assert out["icao"] == "KDYB"
    assert out["wind_dir_deg"] == 250
    assert out["wind_speed_kt"] == 12
    assert out["wind_gust_kt"] == 18
    assert out["temp_c"] == 22.0
    # 1017.95 hPa converts to ~30.06 inHg (33.8639 hPa/inHg).
    assert abs(out["altimeter_inhg"] - 30.06) < 0.01
    assert "25012G18KT" in out["raw_ob"]


def test_parse_passes_through_inhg_when_already_inhg():
    """If a future AWC change starts returning inHg directly, our
    >100 detector preserves the value (no double conversion)."""
    raw = dict(_SAMPLE_KDYB, altim=30.05)
    out = parse_metar_json([raw])
    assert abs(out["altimeter_inhg"] - 30.05) < 1e-6


def test_parse_handles_missing_altim():
    raw = dict(_SAMPLE_KDYB)
    raw.pop("altim")
    out = parse_metar_json([raw])
    assert out["altimeter_inhg"] is None


def test_parse_returns_none_on_empty():
    assert parse_metar_json([]) is None
    assert parse_metar_json([None, None]) is None  # type: ignore[list-item]


def test_fetch_hits_network_once_then_caches():
    calls = {"n": 0}

    def fake_http(icao):
        calls["n"] += 1
        return [_SAMPLE_KDYB]

    with patch.object(metar_mod, "_http_get", side_effect=fake_http):
        a = fetch_metar("KDYB")
        b = fetch_metar("KDYB")
    assert a == b
    assert calls["n"] == 1


def test_fetch_returns_stale_on_network_error():
    with patch.object(metar_mod, "_http_get", return_value=[_SAMPLE_KDYB]):
        first = fetch_metar("KDYB")
    # Next call fails — should still return the stale cached payload.
    with patch.object(metar_mod, "_http_get",
                       side_effect=ConnectionError("offline")):
        # Force cache expiry so we go down the network path.
        ts, payload = metar_mod._CACHE["KDYB"]
        metar_mod._CACHE["KDYB"] = (ts - 10000.0, payload)
        second = fetch_metar("KDYB")
    assert second == first
    assert second["wind_dir_deg"] == 250


def test_fetch_none_on_unknown_icao_with_empty_cache():
    with patch.object(metar_mod, "_http_get", return_value=[]):
        assert fetch_metar("ZZZZ") is None


def test_fetch_blank_input_returns_none():
    assert fetch_metar("") is None
    assert fetch_metar(None) is None  # type: ignore[arg-type]
