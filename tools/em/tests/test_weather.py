"""Phase 4d — tests for the NOAA AWC METAR client.

We mock urllib.request.urlopen so tests never hit the live API. The mock
returns canonical AWC payloads for known idents (KAUS), an empty body for
unknown stations (NOAA's "no obs" signal), a network error for one ident,
and malformed JSON for another. The full matrix exercises parsing,
caching, fallback, and the force-refresh path.
"""

from __future__ import annotations

import io
import json
import time
from unittest.mock import patch
from urllib.error import URLError

import pytest

from services import weather
from services.weather import (
    MetarObservation,
    clear_cache,
    get_metar,
    _parse,
    HPA_TO_INHG,
)


# ---------------------------------------------------------------------------
# Canonical NOAA AWC payload — pulled from a real KAUS observation, trimmed
# to the fields our parser reads.
# ---------------------------------------------------------------------------
KAUS_PAYLOAD = [{
    "icaoId":      "KAUS",
    "name":        "Austin/Bergstrom Intl, TX, US",
    "obsTime":     1778687580,
    "reportTime":  "2026-05-13T16:00:00.000Z",
    "temp":        27.2,
    "dewp":        17.8,
    "altim":       1019.7,        # hPa  → 30.11 inHg
    "wdir":        200,
    "wspd":        7,
    "wgst":        None,
    "visib":       "10+",
    "cover":       "CLR",
    "fltCat":      "VFR",
    "rawOb":       "METAR KAUS 131553Z 20007KT 10SM CLR 27/18 A3011 RMK AO2 SLP190 T02720178",
    "clouds":      [],
    "lat":         30.1831,
    "lon":         -97.6806,
    "elev":        148,
    "metarType":   "METAR",
    "qcField":     4,
    "slp":         1019,
    "receiptTime": "2026-05-13T15:57:44.353Z",
}]

KJFK_GUSTY_PAYLOAD = [{
    "icaoId":      "KJFK",
    "name":        "New York/JF Kennedy Intl, NY, US",
    "obsTime":     1778687460,
    "reportTime":  "2026-05-13T16:00:00.000Z",
    "temp":        16.7,
    "dewp":        9.4,
    "altim":       1014.6,
    "wdir":        180,
    "wspd":        18,
    "wgst":        28,                       # gust value present
    "visib":       "10+",
    "cover":       "BKN",
    "fltCat":      "VFR",
    "rawOb":       "METAR KJFK 131551Z 18018G28KT 10SM FEW070 BKN100 BKN160 BKN250 17/09 A2996",
}]


def _mock_response(body: bytes):
    """Build an object urlopen() returns. Needs .read() + context-manager
    protocol. Mocking the full io.BytesIO is too much — fake the minimum."""
    class _R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return body
    return _R()


def _fake_urlopen(payload_by_icao: dict, *, network_error_for: str | None = None, bad_json_for: str | None = None):
    """Return a urlopen-mock that dispatches by ICAO in the URL."""
    def _impl(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        # Extract the ids=... query value
        ident = ""
        if "ids=" in url:
            ident = url.split("ids=")[1].split("&")[0]
        if network_error_for and ident == network_error_for:
            raise URLError("simulated network failure")
        if bad_json_for and ident == bad_json_for:
            return _mock_response(b"<<< not json >>>")
        body = payload_by_icao.get(ident, [])
        # Empty result is signalled by an empty body, matching AWC's actual behavior.
        if not body:
            return _mock_response(b"")
        return _mock_response(json.dumps(body).encode("utf-8"))
    return _impl


@pytest.fixture(autouse=True)
def _isolate_cache():
    """Make sure each test starts with an empty in-process cache."""
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# Parser unit tests
# ---------------------------------------------------------------------------

class TestParser:
    def test_parses_canonical_kaus(self):
        obs = _parse(KAUS_PAYLOAD[0])
        assert obs.icao == "KAUS"
        assert obs.station_name == "Austin/Bergstrom Intl, TX, US"
        assert obs.temp_c == 27.2
        assert obs.dewpoint_c == 17.8
        # 1019.7 hPa * 0.02953 ≈ 30.11
        assert obs.altimeter_inhg == pytest.approx(30.11, abs=0.01)
        assert obs.wind_dir_deg == 200
        assert obs.wind_speed_kt == 7
        assert obs.wind_gust_kt is None
        assert obs.flight_category == "VFR"
        assert obs.sky_cover == "CLR"
        assert obs.raw.startswith("METAR KAUS")

    def test_parses_gusty_kjfk(self):
        obs = _parse(KJFK_GUSTY_PAYLOAD[0])
        assert obs.wind_gust_kt == 28
        assert obs.wind_speed_kt == 18
        assert obs.sky_cover == "BKN"

    def test_altimeter_conversion_factor(self):
        """Re-check the hPa→inHg constant against the documented 0.02953 ratio."""
        # 1013.25 hPa is the ICAO standard, equivalent to 29.92126 inHg.
        approx = 1013.25 * HPA_TO_INHG
        assert approx == pytest.approx(29.92, abs=0.01)

    def test_missing_fields_become_none(self):
        """A skeletal AWC record (most fields absent) should not crash the parser."""
        obs = _parse({"icaoId": "KXYZ"})
        assert obs.icao == "KXYZ"
        assert obs.temp_c is None
        assert obs.dewpoint_c is None
        assert obs.altimeter_inhg is None
        assert obs.wind_speed_kt is None
        assert obs.flight_category is None


# ---------------------------------------------------------------------------
# MetarObservation dataclass tests
# ---------------------------------------------------------------------------

class TestMetarObservation:
    def test_age_seconds(self):
        obs = _parse({"icaoId": "K", "obsTime": int(time.time()) - 120})
        assert 115 <= obs.age_seconds <= 130

    def test_age_seconds_none_when_no_obs_time(self):
        obs = _parse({"icaoId": "K"})
        assert obs.age_seconds is None

    def test_to_dict_is_json_safe(self):
        """The dcc.Store roundtrip needs this to JSON-encode cleanly."""
        obs = _parse(KAUS_PAYLOAD[0])
        d = obs.to_dict()
        round_tripped = json.loads(json.dumps(d))
        assert round_tripped["icao"] == "KAUS"
        assert round_tripped["altimeter_inhg"] == pytest.approx(30.11, abs=0.01)


# ---------------------------------------------------------------------------
# get_metar — network + cache integration
# ---------------------------------------------------------------------------

class TestGetMetar:
    def test_happy_path_kaus(self):
        with patch("services.weather.urllib.request.urlopen",
                   side_effect=_fake_urlopen({"KAUS": KAUS_PAYLOAD})):
            obs = get_metar("KAUS")
        assert obs is not None
        assert obs.icao == "KAUS"
        assert obs.temp_c == 27.2

    def test_empty_body_returns_none(self):
        """AWC returns HTTP 200 with empty body when the station has no obs."""
        with patch("services.weather.urllib.request.urlopen",
                   side_effect=_fake_urlopen({"00AA": []})):
            obs = get_metar("00AA")
        assert obs is None

    def test_unknown_station_returns_none(self):
        with patch("services.weather.urllib.request.urlopen",
                   side_effect=_fake_urlopen({})):
            obs = get_metar("KZZZZ")
        assert obs is None

    def test_network_error_returns_none(self):
        with patch("services.weather.urllib.request.urlopen",
                   side_effect=_fake_urlopen({}, network_error_for="KAUS")):
            obs = get_metar("KAUS")
        assert obs is None

    def test_malformed_json_returns_none(self):
        with patch("services.weather.urllib.request.urlopen",
                   side_effect=_fake_urlopen({}, bad_json_for="KAUS")):
            obs = get_metar("KAUS")
        assert obs is None

    def test_normalizes_case_and_whitespace(self):
        with patch("services.weather.urllib.request.urlopen",
                   side_effect=_fake_urlopen({"KAUS": KAUS_PAYLOAD})):
            assert get_metar(" kaus ").icao == "KAUS"

    def test_empty_input_returns_none_without_network(self):
        """An empty ICAO must not even attempt a network call."""
        with patch("services.weather.urllib.request.urlopen") as m:
            assert get_metar("") is None
            assert get_metar(None) is None
            assert m.call_count == 0


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------

class TestCache:
    def test_second_call_uses_cache(self):
        """Two calls inside TTL → exactly one network call."""
        with patch("services.weather.urllib.request.urlopen",
                   side_effect=_fake_urlopen({"KAUS": KAUS_PAYLOAD})) as m:
            a = get_metar("KAUS")
            b = get_metar("KAUS")
        assert a is not None and b is not None
        assert a == b
        assert m.call_count == 1

    def test_force_bypasses_cache(self):
        with patch("services.weather.urllib.request.urlopen",
                   side_effect=_fake_urlopen({"KAUS": KAUS_PAYLOAD})) as m:
            get_metar("KAUS")
            get_metar("KAUS", force=True)
        assert m.call_count == 2

    def test_negative_result_is_cached(self):
        """An empty-body 'no obs' answer should also be cached — we don't
        want to re-hammer NOAA for the same private strip on every click."""
        with patch("services.weather.urllib.request.urlopen",
                   side_effect=_fake_urlopen({"00AA": []})) as m:
            assert get_metar("00AA") is None
            assert get_metar("00AA") is None
        assert m.call_count == 1

    def test_network_failure_is_not_cached(self):
        """Transient errors should retry on the next call, not poison the cache."""
        with patch("services.weather.urllib.request.urlopen",
                   side_effect=_fake_urlopen({}, network_error_for="KAUS")) as m:
            assert get_metar("KAUS") is None
            assert get_metar("KAUS") is None
        # Both calls hit the network — error was not cached.
        assert m.call_count == 2

    def test_ttl_expiry_triggers_refetch(self):
        """Past the TTL window, a fresh call should refetch."""
        with patch("services.weather.urllib.request.urlopen",
                   side_effect=_fake_urlopen({"KAUS": KAUS_PAYLOAD})) as m:
            get_metar("KAUS")
            # Backdate the cache entry so it appears stale.
            stale_at = time.time() - (weather.CACHE_TTL_S + 1)
            weather._CACHE["KAUS"] = (stale_at, weather._CACHE["KAUS"][1])
            get_metar("KAUS")
        assert m.call_count == 2

    def test_clear_cache_resets_everything(self):
        with patch("services.weather.urllib.request.urlopen",
                   side_effect=_fake_urlopen({"KAUS": KAUS_PAYLOAD})) as m:
            get_metar("KAUS")
            clear_cache()
            get_metar("KAUS")
        assert m.call_count == 2
