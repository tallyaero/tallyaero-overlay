"""Tests for core.land_cover_osm — suitable-land classification,
geometry conversion, and Overpass fetch (mocked)."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from core import land_cover_osm as lc


# === classify_feature =======================================================

def test_classify_farmland_is_suitable():
    assert lc.classify_feature({"landuse": "farmland"}) == "suitable"


def test_classify_meadow_is_suitable():
    assert lc.classify_feature({"landuse": "meadow"}) == "suitable"


def test_classify_grass_is_suitable():
    assert lc.classify_feature({"landuse": "grass"}) == "suitable"


def test_classify_pasture_is_suitable():
    assert lc.classify_feature({"landuse": "pasture"}) == "suitable"


def test_classify_natural_grassland_is_suitable():
    assert lc.classify_feature({"natural": "grassland"}) == "suitable"


def test_classify_natural_heath_is_suitable():
    assert lc.classify_feature({"natural": "heath"}) == "suitable"


def test_classify_water_is_not_suitable():
    """Hazard tags should NOT be returned as suitable."""
    assert lc.classify_feature({"natural": "water"}) is None


def test_classify_forest_is_not_suitable():
    assert lc.classify_feature({"landuse": "forest"}) is None
    assert lc.classify_feature({"natural": "wood"}) is None


def test_classify_residential_is_not_suitable():
    assert lc.classify_feature({"landuse": "residential"}) is None
    assert lc.classify_feature({"landuse": "commercial"}) is None


def test_classify_empty_tags():
    assert lc.classify_feature({}) is None
    assert lc.classify_feature(None) is None


# === _element_to_geojson_geom ==============================================

def test_way_geom_polygon():
    elem = {
        "type": "way",
        "geometry": [
            {"lat": 33.0, "lon": -80.0},
            {"lat": 33.1, "lon": -80.0},
            {"lat": 33.1, "lon": -79.9},
            {"lat": 33.0, "lon": -79.9},
        ],
    }
    geom = lc._element_to_geojson_geom(elem)
    assert geom["type"] == "Polygon"
    coords = geom["coordinates"][0]
    # GeoJSON is [lon, lat]
    assert coords[0] == [-80.0, 33.0]
    # Auto-closed (last == first)
    assert coords[0] == coords[-1]


def test_way_geom_too_short_returns_none():
    elem = {"type": "way", "geometry": [
        {"lat": 33.0, "lon": -80.0},
        {"lat": 33.1, "lon": -80.0},
    ]}
    assert lc._element_to_geojson_geom(elem) is None


def test_relation_geom_multipolygon():
    elem = {
        "type": "relation",
        "members": [
            {"role": "outer", "geometry": [
                {"lat": 33.0, "lon": -80.0},
                {"lat": 33.1, "lon": -80.0},
                {"lat": 33.1, "lon": -79.9},
                {"lat": 33.0, "lon": -79.9},
            ]},
            {"role": "outer", "geometry": [
                {"lat": 34.0, "lon": -81.0},
                {"lat": 34.1, "lon": -81.0},
                {"lat": 34.1, "lon": -80.9},
                {"lat": 34.0, "lon": -80.9},
            ]},
        ],
    }
    geom = lc._element_to_geojson_geom(elem)
    assert geom["type"] == "MultiPolygon"
    assert len(geom["coordinates"]) == 2


def test_relation_single_outer_is_polygon():
    elem = {
        "type": "relation",
        "members": [
            {"role": "outer", "geometry": [
                {"lat": 33.0, "lon": -80.0},
                {"lat": 33.1, "lon": -80.0},
                {"lat": 33.1, "lon": -79.9},
                {"lat": 33.0, "lon": -79.9},
            ]},
            # Inner members are dropped — pilots care only about the
            # outer landable shell, not the holes.
            {"role": "inner", "geometry": [
                {"lat": 33.04, "lon": -79.97},
                {"lat": 33.06, "lon": -79.97},
                {"lat": 33.06, "lon": -79.93},
                {"lat": 33.04, "lon": -79.93},
            ]},
        ],
    }
    geom = lc._element_to_geojson_geom(elem)
    assert geom["type"] == "Polygon"


# === _bbox_cache_key ========================================================

def test_bbox_cache_key_rounding():
    """Nearby bboxes should share a cache key (0.05° rounding)."""
    k1 = lc._bbox_cache_key(33.001, -80.001, 33.499, -79.499)
    k2 = lc._bbox_cache_key(33.000, -80.000, 33.500, -79.500)
    assert k1 == k2


def test_bbox_cache_key_far_apart_differs():
    k1 = lc._bbox_cache_key(33.0, -80.0, 33.5, -79.5)
    k2 = lc._bbox_cache_key(40.0, -100.0, 40.5, -99.5)
    assert k1 != k2


# === fetch_suitable_land (mocked) ===========================================

def _mock_overpass_payload():
    return {
        "elements": [
            {
                "type": "way",
                "tags": {"landuse": "farmland", "name": "Hawkins Farm"},
                "geometry": [
                    {"lat": 33.0, "lon": -80.0},
                    {"lat": 33.1, "lon": -80.0},
                    {"lat": 33.1, "lon": -79.9},
                    {"lat": 33.0, "lon": -79.9},
                ],
            },
            {
                # Hazard tag — should be silently dropped
                "type": "way",
                "tags": {"natural": "water"},
                "geometry": [
                    {"lat": 33.2, "lon": -80.2},
                    {"lat": 33.21, "lon": -80.2},
                    {"lat": 33.21, "lon": -80.19},
                    {"lat": 33.2, "lon": -80.19},
                ],
            },
            {
                "type": "way",
                "tags": {"natural": "grassland"},
                "geometry": [
                    {"lat": 33.3, "lon": -80.3},
                    {"lat": 33.31, "lon": -80.3},
                    {"lat": 33.31, "lon": -80.29},
                    {"lat": 33.3, "lon": -80.29},
                ],
            },
        ],
    }


def test_fetch_suitable_land_classifies_correctly(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "_CACHE_ROOT", tmp_path)
    with patch.object(lc, "_fetch_overpass",
                      return_value=_mock_overpass_payload()):
        result = lc.fetch_suitable_land(33.0, -80.5, 33.5, -79.5)
    assert result["type"] == "FeatureCollection"
    # Only farmland + grassland make it through; water is dropped
    assert len(result["features"]) == 2
    cats = [f["properties"]["landuse"] or f["properties"]["natural"]
            for f in result["features"]]
    assert "farmland" in cats
    assert "grassland" in cats


def test_fetch_suitable_land_handles_total_failure(tmp_path, monkeypatch):
    """When Overpass is unreachable, return empty FeatureCollection."""
    monkeypatch.setattr(lc, "_CACHE_ROOT", tmp_path)
    with patch.object(lc, "_fetch_overpass", return_value=None):
        result = lc.fetch_suitable_land(33.0, -80.5, 33.5, -79.5)
    assert result["type"] == "FeatureCollection"
    assert result["features"] == []


def test_fetch_suitable_land_cache_roundtrip(tmp_path, monkeypatch):
    """Second call with same bbox hits cache, doesn't refetch."""
    monkeypatch.setattr(lc, "_CACHE_ROOT", tmp_path)
    with patch.object(lc, "_fetch_overpass",
                      return_value=_mock_overpass_payload()) as mock:
        lc.fetch_suitable_land(33.0, -80.5, 33.5, -79.5)
        lc.fetch_suitable_land(33.0, -80.5, 33.5, -79.5)   # cache hit
    assert mock.call_count == 1


# === back-compat shim ======================================================

def test_fetch_land_cover_back_compat(tmp_path, monkeypatch):
    """Legacy callers still get a category-keyed dict."""
    monkeypatch.setattr(lc, "_CACHE_ROOT", tmp_path)
    with patch.object(lc, "_fetch_overpass",
                      return_value=_mock_overpass_payload()):
        result = lc.fetch_land_cover(33.0, -80.5, 33.5, -79.5)
    assert "suitable" in result
    assert result["suitable"]["type"] == "FeatureCollection"


def test_styles_are_green_only():
    """Suitable land renders in the same green family as the slope
    layer so both signals read as one composite "landable" wash."""
    style = lc.SUITABLE_LAND_STYLE
    # Tailwind green-500 family
    assert style["fillColor"].lower() == "#22c55e"
    assert 0 < style["fillOpacity"] < 0.5
