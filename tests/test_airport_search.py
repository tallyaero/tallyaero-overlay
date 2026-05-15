"""Tests for core.airport_search — ranked airport lookup + waypoint resolution.

Uses a small in-memory airport list so tests don't depend on the full
49k airport_data load.
"""
from __future__ import annotations

import pytest
from core.airport_search import (
    search_airports, airport_label, resolve_waypoint, _score,
)


@pytest.fixture
def sample_airports():
    return [
        {"id": "KDYB", "icao": "KDYB", "local": "DYB",
         "name": "Summerville Airport", "municipality": "Summerville",
         "state": "South Carolina", "country": "United States"},
        {"id": "KCHS", "icao": "KCHS", "iata": "CHS",
         "name": "Charleston International Airport",
         "municipality": "Charleston",
         "state": "South Carolina", "country": "United States"},
        {"id": "KSAV", "icao": "KSAV", "iata": "SAV",
         "name": "Savannah/Hilton Head International",
         "municipality": "Savannah",
         "state": "Georgia", "country": "United States"},
        {"id": "KJFK", "icao": "KJFK", "iata": "JFK",
         "name": "John F Kennedy International Airport",
         "municipality": "New York",
         "state": "New York", "country": "United States"},
        {"id": "LFPG", "icao": "LFPG", "iata": "CDG",
         "name": "Paris-Charles de Gaulle Airport",
         "municipality": "Paris", "country": "France"},
    ]


def test_score_exact_icao_top_tier(sample_airports):
    ap = sample_airports[0]   # KDYB
    assert _score(ap, "kdyb") == 1000


def test_score_prefix_on_code(sample_airports):
    ap = sample_airports[0]
    assert _score(ap, "kdy") == 500


def test_score_local_lid_exact_match(sample_airports):
    """A pilot typing 'DYB' (the FAA LID) should still hit KDYB."""
    ap = sample_airports[0]
    assert _score(ap, "dyb") == 1000


def test_score_prefix_on_city(sample_airports):
    ap = sample_airports[0]   # Summerville
    assert _score(ap, "summer") == 250


def test_score_no_match(sample_airports):
    ap = sample_airports[0]
    assert _score(ap, "tokyo") == 0


def test_search_too_short_returns_empty(sample_airports):
    assert search_airports(sample_airports, "k") == []
    assert search_airports(sample_airports, "") == []


def test_search_exact_code_ranks_first(sample_airports):
    hits = search_airports(sample_airports, "KDYB")
    assert hits[0]["id"] == "KDYB"


def test_search_city_substring(sample_airports):
    hits = search_airports(sample_airports, "summerville")
    assert any(h["id"] == "KDYB" for h in hits)
    # And Summerville is the top hit
    assert hits[0]["id"] == "KDYB"


def test_search_city_partial(sample_airports):
    """Typing 'savan' should surface KSAV."""
    hits = search_airports(sample_airports, "savan")
    assert any(h["id"] == "KSAV" for h in hits)


def test_search_iata_only(sample_airports):
    """A pilot typing 'CDG' (IATA) should find LFPG."""
    hits = search_airports(sample_airports, "CDG")
    assert hits[0]["id"] == "LFPG"


def test_search_respects_limit(sample_airports):
    hits = search_airports(sample_airports, "international", limit=2)
    assert len(hits) <= 2


def test_label_format_us(sample_airports):
    label = airport_label(sample_airports[0])
    assert "KDYB" in label
    assert "Summerville" in label
    assert "South Carolina" in label


def test_label_format_international(sample_airports):
    label = airport_label(sample_airports[-1])
    assert "LFPG" in label
    assert "Paris" in label
    assert "France" in label


def test_resolve_exact_code(sample_airports):
    ap = resolve_waypoint(sample_airports, "KDYB")
    assert ap is not None
    assert ap["id"] == "KDYB"


def test_resolve_lid(sample_airports):
    """FAA LID resolves to the parent airport."""
    ap = resolve_waypoint(sample_airports, "DYB")
    assert ap is not None
    assert ap["id"] == "KDYB"


def test_resolve_iata(sample_airports):
    ap = resolve_waypoint(sample_airports, "JFK")
    assert ap is not None
    assert ap["id"] == "KJFK"


def test_resolve_fuzzy_fallback(sample_airports):
    """If no exact code match, fall back to best fuzzy hit."""
    ap = resolve_waypoint(sample_airports, "savannah")
    assert ap is not None
    assert ap["id"] == "KSAV"


def test_resolve_unknown_returns_none(sample_airports):
    assert resolve_waypoint(sample_airports, "xxxxx") is None
    assert resolve_waypoint(sample_airports, "") is None
    assert resolve_waypoint(sample_airports, None) is None
