"""
TallyAero EM Diagram — aircraft-editor page callbacks.

This module hosts the entire CRUD surface for `/edit-aircraft`:
load, apply-defaults, unit conversion, G-limits add/render/update,
stall-speeds add/render/update, single-engine-limits, OEI performance,
engine options, clear-all, save-to-file, and upload-from-file.

Phase 1d relocated this block from app.py (~1,659 lines) without splitting
or rewriting any callback. Every @app.callback below mirrors its original.

register(app) installs all 22 callbacks.
"""

from __future__ import annotations

import base64
import copy
import json
import os

import dash
from dash import ctx, dcc, html
import dash_bootstrap_components as dbc
from dash.dependencies import ALL, Input, Output, State
from dash.exceptions import PreventUpdate

from core import (
    KTS_TO_MPH,
    aircraft_data,
    dprint,
    log_feature,
)


def register(app):
    """Install every aircraft-editor callback on the given Dash app."""

    # ─── Phase 5T: aircraft-search options + auto-load wiring ───────────
    @app.callback(
        Output("aircraft-search", "options"),
        Input("aircraft-data-store", "data"),
    )
    def _populate_aircraft_search_options(data):
        """Populate the dropdown with every aircraft in the store, alpha-sorted."""
        if not data:
            return []
        return [{"label": name, "value": name} for name in sorted(data.keys())]

    @app.callback(
        Output("aircraft-search", "value"),
        Input("editing-aircraft", "data"),
        prevent_initial_call=False,
    )
    def _autoload_from_editing_store(editing):
        """If the main page handed us an aircraft name (via the editing-aircraft
        Store), pre-select it in the search dropdown. The existing
        load_aircraft_full callback fires on that value and fills the form."""
        if not editing:
            raise PreventUpdate
        return editing

    @app.callback(
        Output("edit-page-title", "children"),
        Input("aircraft-search", "value"),
        Input("aircraft-name", "value"),
    )
    def _update_edit_page_title(loaded_name, current_name):
        """Title reflects the currently-loaded aircraft. Falls back to the
        name typed into the form, otherwise 'New aircraft'."""
        if loaded_name and loaded_name == current_name:
            return f"Editing · {loaded_name}"
        if loaded_name:
            return f"Editing · {loaded_name} (renamed to {current_name})" if current_name else f"Editing · {loaded_name}"
        if current_name:
            return f"New · {current_name}"
        return "New aircraft profile"

    @app.callback(
        Output("aircraft-name", "value", allow_duplicate=True),
        Output("search-result", "children", allow_duplicate=True),
        Output("aircraft-search", "value", allow_duplicate=True),
        Input("duplicate-aircraft-button", "n_clicks"),
        State("aircraft-name", "value"),
        prevent_initial_call=True,
    )
    def _duplicate_current_aircraft(n_clicks, current_name):
        """Reset the dropdown selection (so future saves don't overwrite the
        original) and append ' (copy)' to the name. The form retains every
        other value, so the user can tweak from a known-good baseline."""
        if not n_clicks:
            raise PreventUpdate
        if not current_name:
            return dash.no_update, "Load an aircraft first, then click Duplicate.", dash.no_update
        new_name = f"{current_name} (copy)"
        return new_name, f"Duplicated as '{new_name}'. Edit and Save when ready.", None

    @app.callback(
        [
            Output("aircraft-name", "value"),
            Output("aircraft-type", "value"),
            Output("gear-type", "value"),
            Output("engine-count", "value"),
            Output("wing-area", "value"),
            Output("aspect-ratio", "value"),
            Output("cd0", "value"),
            Output("oswald-efficiency", "value"),
            Output("stored-flap-configs", "data"),
            Output("stored-g-limits", "data"),
            Output("g-limits-container", "children"),
            Output("stored-stall-speeds", "data"),
            Output("stall-speeds-container", "children"),
            Output("stored-single-engine-limits", "data"),
            Output("stored-engine-options", "data"),
            Output("engine-options-container", "children"),
            Output("empty-weight", "value"),
            Output("max-weight", "value"),
            Output("best-glide", "value"),
            Output("best-glide-ratio", "value"),
            Output("seats", "value"),
            Output("cg-fwd", "value"),
            Output("cg-aft", "value"),
            Output({"type": "vfe-input", "config": "takeoff"}, "value"),
            Output({"type": "vfe-input", "config": "landing"}, "value"),
            Output({"type": "clmax-input", "config": "clean"}, "value"),
            Output({"type": "clmax-input", "config": "takeoff"}, "value"),
            Output({"type": "clmax-input", "config": "landing"}, "value"),
            Output("fuel-capacity-gal", "value"),
            Output("fuel-weight-per-gal", "value"),
            Output("arc-white-bottom", "value"),
            Output("arc-white-top", "value"),
            Output("arc-green-bottom", "value"),
            Output("arc-green-top", "value"),
            Output("arc-yellow-bottom", "value"),
            Output("arc-yellow-top", "value"),
            Output("arc-red", "value"),
            Output("prop-static-factor", "value"),
            Output("prop-vmax-kts", "value"),
            Output("stored-oei-performance", "data"),
            Output("max-altitude", "value"),
            Output("vne", "value"),
            Output("vno", "value"),
            Output("search-result", "children", allow_duplicate=True),
        ],
        Input("aircraft-search", "value"),
        prevent_initial_call=True,
    )
    def load_aircraft_full(selected_name):
        if not selected_name or selected_name not in aircraft_data:
            raise PreventUpdate

        # Track aircraft selection with details
        ac = aircraft_data[selected_name]
        log_feature('aircraft_select', {
            'aircraft': selected_name,
            'type': ac.get('type', 'unknown'),
            'engine_count': ac.get('engine_count', 1),
            'category': ac.get('category', 'unknown')
        })

        stored_flap_configs = ac.get("configuration_options", {}).get("flaps", [])

        stored_g_limits = []
        for category, configs in ac.get("G_limits", {}).items():
            for config_name, values in configs.items():
                if isinstance(values, dict):  # new format
                    stored_g_limits.append({
                        "category": category,
                        "config": config_name,
                        "positive": values.get("positive"),
                        "negative": values.get("negative")
                    })
                else:  # old format fallback (single float)
                    stored_g_limits.append({
                        "category": category,
                        "config": config_name,
                        "positive": values,
                        "negative": None
                    })

        # --- Stall Speeds
        stored_stall_speeds = []
        stall_data = ac.get("stall_speeds", {})
        for config_name, config_data in stall_data.items():
            weights = config_data.get("weights", [])
            speeds = config_data.get("speeds", [])
            for w, s in zip(weights, speeds):
                stored_stall_speeds.append({
                    "config": config_name,
                    "gear": "up",
                    "weight": w,
                    "speed": s
                })

        # --- Single Engine Limits
        stored_single_engine_limits = []

        # Only populate if aircraft has more than 1 engine
        if ac.get("engine_count", 1) >= 2:
            se_data = ac.get("single_engine_limits", {})
            for limit_type, values in se_data.items():
                if limit_type not in ("Vmca", "Vyse", "Vxse"):
                    continue  # Skip best_glide, best_glide_ratio, etc.

                if isinstance(values, dict):
                    for config_key, val in values.items():
                        parts = config_key.split("_")
                        flap = parts[0] if len(parts) > 0 else ""
                        gear = parts[1] if len(parts) > 1 else ""
                        stored_single_engine_limits.append({
                            "limit_type": limit_type,
                            "value": val,
                            "flap_config": flap,
                            "gear_config": gear
                        })
                else:
                    stored_single_engine_limits.append({
                        "limit_type": limit_type,
                        "value": values,
                        "flap_config": "",
                        "gear_config": ""
                    })

            
        # --- Engine Options
        stored_engine_options = []
        for eng_name, eng_info in ac.get("engine_options", {}).items():
            power = eng_info.get("power_curve", {})
            stored_engine_options.append({
                "name": eng_name,
                "horsepower": eng_info.get("horsepower"),
                "power_curve_sea_level": power.get("sea_level_max"),
                "power_curve_derate": power.get("derate_per_1000ft"),
            })


        # Container children are left empty - the render callbacks will
        # populate them from the stored data (stored_g_limits, etc.)
        g_limit_fields = []
        stall_speed_fields = []
        engine_fields = []

        # --- Prop Thrust Decay
        prop_decay = ac.get("prop_thrust_decay", {})
        t_static = prop_decay.get("T_static_factor")
        v_max_kts = prop_decay.get("V_max_kts")

        # --- Fuel
        fuel_capacity = ac.get("fuel_capacity_gal")
        fuel_weight = ac.get("fuel_weight_per_gal")

        # --- Airspeed Arcs
        arcs = ac.get("arcs", {})
        white_bottom, white_top = (arcs.get("white", [None, None]) + [None, None])[:2]
        green_bottom, green_top = (arcs.get("green", [None, None]) + [None, None])[:2]
        yellow_bottom, yellow_top = (arcs.get("yellow", [None, None]) + [None, None])[:2]
        red = arcs.get("red")

        # --- Service Ceiling
        max_altitude = next(iter(ac.get("engine_options", {}).values()), {}).get("power_curve", {}).get("max_altitude", None)

        # --- Flatten OEI Performance
        oei_flat = []
        for eng_name, eng_data in ac.get("engine_options", {}).items():
            for config_key, config_data in eng_data.get("oei_performance", {}).items():
                for prop_condition, values in config_data.items():
                    oei_flat.append({
                        "engine": eng_name,
                        "config": config_key,  # Use "config" for consistency with add/render callbacks
                        "prop_condition": prop_condition,
                        "max_power_fraction": values.get("max_power_fraction"),
                    })
    
        # --- Return everything
        return (
            selected_name,  # aircraft-name
            ac.get("type"),
            ac.get("gear_type", "fixed"),
            ac.get("engine_count"),
            ac.get("wing_area"),  # wing-area
            ac.get("aspect_ratio"),  # aspect-ratio
            ac.get("CD0"),  # cd0
            ac.get("e"),  # oswald-efficiency
            stored_flap_configs,  # stored-flap-configs
            stored_g_limits,  # stored-g-limits
            g_limit_fields,  # g-limits-container
            stored_stall_speeds,  # stored-stall-speeds
            stall_speed_fields,  # stall-speeds-container
            stored_single_engine_limits,  # stored-single-engine-limits
            stored_engine_options,  # stored-engine-options
            engine_fields,  # engine-options-container
            ac.get("empty_weight"),  # empty-weight
            ac.get("max_weight"),
            ac.get("single_engine_limits", {}).get("best_glide"),
            ac.get("single_engine_limits", {}).get("best_glide_ratio"),
            ac.get("seats"),  # seats
            ac.get("cg_range", [None, None])[0],  # cg-fwd
            ac.get("cg_range", [None, None])[1],  # cg-aft
            ac.get("Vfe", {}).get("takeoff"),  # vfe-input (takeoff)
            ac.get("Vfe", {}).get("landing"),  # vfe-input (landing)
            ac.get("CL_max", {}).get("clean"),  # clmax-input (clean)
            ac.get("CL_max", {}).get("takeoff"),  # clmax-input (takeoff)
            ac.get("CL_max", {}).get("landing"),  # clmax-input (landing)
            ac.get("fuel_capacity_gal"),  # fuel-capacity-gal
            ac.get("fuel_weight_per_gal"),  # fuel-weight-per-gal
            ac.get("arcs", {}).get("white", [None, None])[0],  # arc-white-bottom
            ac.get("arcs", {}).get("white", [None, None])[1],  # arc-white-top
            ac.get("arcs", {}).get("green", [None, None])[0],  # arc-green-bottom
            ac.get("arcs", {}).get("green", [None, None])[1],  # arc-green-top
            ac.get("arcs", {}).get("yellow", [None, None])[0],  # arc-yellow-bottom
            ac.get("arcs", {}).get("yellow", [None, None])[1],  # arc-yellow-top
            ac.get("arcs", {}).get("red"),  # arc-red
            ac.get("prop_thrust_decay", {}).get("T_static_factor"),  # prop-static-factor
            ac.get("prop_thrust_decay", {}).get("V_max_kts"),  # prop-vmax-kts
            oei_flat,  # stored-oei-performance
            ac.get("max_altitude"),
            ac.get("Vne"),  # vne
            ac.get("Vno"),  # vno
            f"Loaded: {selected_name}",  # search-result
        )

    @app.callback(
        # Basic info
        Output("aircraft-type", "value", allow_duplicate=True),
        Output("gear-type", "value", allow_duplicate=True),
        Output("engine-count", "value", allow_duplicate=True),
        # Aerodynamics
        Output("wing-area", "value", allow_duplicate=True),
        Output("aspect-ratio", "value", allow_duplicate=True),
        Output("cd0", "value", allow_duplicate=True),
        Output("oswald-efficiency", "value", allow_duplicate=True),
        Output("prop-static-factor", "value", allow_duplicate=True),
        Output("prop-vmax-kts", "value", allow_duplicate=True),
        # Weights
        Output("empty-weight", "value", allow_duplicate=True),
        Output("max-weight", "value", allow_duplicate=True),
        Output("seats", "value", allow_duplicate=True),
        Output("fuel-capacity-gal", "value", allow_duplicate=True),
        Output("fuel-weight-per-gal", "value", allow_duplicate=True),
        # Speeds
        Output("vne", "value", allow_duplicate=True),
        Output("vno", "value", allow_duplicate=True),
        Output("best-glide", "value", allow_duplicate=True),
        Output("best-glide-ratio", "value", allow_duplicate=True),
        Output("max-altitude", "value", allow_duplicate=True),
        # Arcs
        Output("arc-white-bottom", "value", allow_duplicate=True),
        Output("arc-white-top", "value", allow_duplicate=True),
        Output("arc-green-bottom", "value", allow_duplicate=True),
        Output("arc-green-top", "value", allow_duplicate=True),
        Output("arc-yellow-bottom", "value", allow_duplicate=True),
        Output("arc-yellow-top", "value", allow_duplicate=True),
        Output("arc-red", "value", allow_duplicate=True),
        # Flaps
        Output({"type": "vfe-input", "config": "takeoff"}, "value", allow_duplicate=True),
        Output({"type": "vfe-input", "config": "landing"}, "value", allow_duplicate=True),
        Output({"type": "clmax-input", "config": "clean"}, "value", allow_duplicate=True),
        Output({"type": "clmax-input", "config": "takeoff"}, "value", allow_duplicate=True),
        Output({"type": "clmax-input", "config": "landing"}, "value", allow_duplicate=True),
        # Stores
        Output("stored-engine-options", "data", allow_duplicate=True),
        Output("stored-g-limits", "data", allow_duplicate=True),
        Output("stored-stall-speeds", "data", allow_duplicate=True),
        Output("stored-oei-performance", "data", allow_duplicate=True),
        # Inputs
        Input("default-trainer", "n_clicks"),
        Input("default-single", "n_clicks"),
        Input("default-highperf", "n_clicks"),
        Input("default-multi", "n_clicks"),
        Input("default-aerobatic", "n_clicks"),
        Input("default-experimental", "n_clicks"),
        prevent_initial_call=True
    )
    def apply_default_performance(trainer, single, highperf, multi, aero, exp):
        triggered = ctx.triggered_id

        # Define comprehensive defaults for each category
        defaults = {
            "default-trainer": {
                # Basic Trainer: C150, C152, PA-28-140, DA20
                "aircraft_type": "single_engine",
                "gear_type": "fixed",
                "engine_count": 1,
                "wing_area": 160,
                "aspect_ratio": 6.8,
                "cd0": 0.028,
                "e": 0.78,
                "t_static": 2.5,
                "vmax": 125,
                "empty_weight": 1100,
                "max_weight": 1670,
                "seats": 2,
                "fuel_capacity": 26,
                "fuel_weight": 6.0,
                "vne": 140,
                "vno": 111,
                "best_glide": 60,
                "glide_ratio": 8.5,
                "ceiling": 14000,
                "arcs": {"white": [42, 85], "green": [48, 111], "yellow": [111, 140], "red": 140},
                "vfe": {"takeoff": 100, "landing": 85},
                "clmax": {"clean": 1.45, "takeoff": 1.7, "landing": 2.0},
                "engine": {"name": "Continental O-200-A", "hp": 100, "derate": 0.03},
                "g_limits": [
                    {"category": "normal", "config": "clean", "positive": 3.8, "negative": -1.52},
                    {"category": "normal", "config": "takeoff", "positive": 2.0, "negative": -1.0},
                    {"category": "normal", "config": "landing", "positive": 2.0, "negative": -1.0},
                ],
                "stall_speeds": [
                    {"config": "clean", "weight": 1670, "speed": 48},
                    {"config": "takeoff", "weight": 1670, "speed": 44},
                    {"config": "landing", "weight": 1670, "speed": 42},
                ],
            },
            "default-single": {
                # Standard Single: C172, PA-28-181, DA40, SR20
                "aircraft_type": "single_engine",
                "gear_type": "fixed",
                "engine_count": 1,
                "wing_area": 174,
                "aspect_ratio": 7.32,
                "cd0": 0.027,
                "e": 0.80,
                "t_static": 2.6,
                "vmax": 163,
                "empty_weight": 1660,
                "max_weight": 2550,
                "seats": 4,
                "fuel_capacity": 56,
                "fuel_weight": 6.0,
                "vne": 163,
                "vno": 129,
                "best_glide": 68,
                "glide_ratio": 9.0,
                "ceiling": 14000,
                "arcs": {"white": [41, 85], "green": [47, 129], "yellow": [129, 163], "red": 163},
                "vfe": {"takeoff": 110, "landing": 85},
                "clmax": {"clean": 1.5, "takeoff": 1.7, "landing": 1.9},
                "engine": {"name": "Lycoming IO-360-L2A", "hp": 180, "derate": 0.03},
                "g_limits": [
                    {"category": "normal", "config": "clean", "positive": 3.8, "negative": -1.52},
                    {"category": "normal", "config": "takeoff", "positive": 2.0, "negative": -1.0},
                    {"category": "normal", "config": "landing", "positive": 2.0, "negative": -1.0},
                ],
                "stall_speeds": [
                    {"config": "clean", "weight": 2550, "speed": 53},
                    {"config": "clean", "weight": 2200, "speed": 49},
                    {"config": "takeoff", "weight": 2550, "speed": 50},
                    {"config": "landing", "weight": 2550, "speed": 47},
                ],
            },
            "default-highperf": {
                # High Performance: C182, Bonanza, Mooney, SR22
                "aircraft_type": "single_engine",
                "gear_type": "retractable",
                "engine_count": 1,
                "wing_area": 175,
                "aspect_ratio": 7.4,
                "cd0": 0.024,
                "e": 0.82,
                "t_static": 2.7,
                "vmax": 200,
                "empty_weight": 2100,
                "max_weight": 3400,
                "seats": 4,
                "fuel_capacity": 92,
                "fuel_weight": 6.0,
                "vne": 200,
                "vno": 165,
                "best_glide": 90,
                "glide_ratio": 10.5,
                "ceiling": 18500,
                "arcs": {"white": [50, 100], "green": [58, 165], "yellow": [165, 200], "red": 200},
                "vfe": {"takeoff": 120, "landing": 100},
                "clmax": {"clean": 1.4, "takeoff": 1.65, "landing": 1.95},
                "engine": {"name": "Continental IO-550-N", "hp": 310, "derate": 0.025},
                "g_limits": [
                    {"category": "normal", "config": "clean", "positive": 3.8, "negative": -1.52},
                    {"category": "normal", "config": "takeoff", "positive": 2.0, "negative": -1.0},
                    {"category": "normal", "config": "landing", "positive": 2.0, "negative": -1.0},
                ],
                "stall_speeds": [
                    {"config": "clean", "weight": 3400, "speed": 63},
                    {"config": "clean", "weight": 2800, "speed": 57},
                    {"config": "takeoff", "weight": 3400, "speed": 58},
                    {"config": "landing", "weight": 3400, "speed": 53},
                ],
            },
            "default-multi": {
                # Light Twin: PA-44, DA42, Baron 58
                "aircraft_type": "multi_engine",
                "gear_type": "retractable",
                "engine_count": 2,
                "wing_area": 183,
                "aspect_ratio": 7.2,
                "cd0": 0.028,
                "e": 0.80,
                "t_static": 2.6,
                "vmax": 202,
                "empty_weight": 2570,
                "max_weight": 3800,
                "seats": 4,
                "fuel_capacity": 110,
                "fuel_weight": 6.0,
                "vne": 202,
                "vno": 169,
                "best_glide": 88,
                "glide_ratio": 9.5,
                "ceiling": 15000,
                "arcs": {"white": [55, 108], "green": [64, 169], "yellow": [169, 202], "red": 202},
                "vfe": {"takeoff": 125, "landing": 108},
                "clmax": {"clean": 1.35, "takeoff": 1.6, "landing": 1.95},
                "engine": {"name": "Lycoming IO-360-A1B6", "hp": 180, "derate": 0.03},
                "g_limits": [
                    {"category": "normal", "config": "clean", "positive": 3.8, "negative": -1.52},
                    {"category": "normal", "config": "takeoff", "positive": 2.0, "negative": -1.0},
                    {"category": "normal", "config": "landing", "positive": 2.0, "negative": -1.0},
                ],
                "stall_speeds": [
                    {"config": "clean", "weight": 3800, "speed": 68},
                    {"config": "clean", "weight": 3200, "speed": 62},
                    {"config": "takeoff", "weight": 3800, "speed": 63},
                    {"config": "landing", "weight": 3800, "speed": 58},
                ],
                "oei": [
                    {"config": "clean_up", "prop_condition": "feathered", "max_power_fraction": 0.5},
                    {"config": "clean_up", "prop_condition": "windmilling", "max_power_fraction": 0.45},
                ],
            },
            "default-aerobatic": {
                # Aerobatic: Extra 300, Pitts, CAP 232, Decathlon
                "aircraft_type": "single_engine",
                "gear_type": "fixed",
                "engine_count": 1,
                "wing_area": 100,
                "aspect_ratio": 5.0,
                "cd0": 0.030,
                "e": 0.75,
                "t_static": 2.8,
                "vmax": 220,
                "empty_weight": 1100,
                "max_weight": 1650,
                "seats": 2,
                "fuel_capacity": 40,
                "fuel_weight": 6.0,
                "vne": 220,
                "vno": 163,
                "best_glide": 100,
                "glide_ratio": 8.0,
                "ceiling": 16000,
                "arcs": {"white": [54, 100], "green": [61, 163], "yellow": [163, 220], "red": 220},
                "vfe": {"takeoff": None, "landing": 100},
                "clmax": {"clean": 1.6, "takeoff": 1.8, "landing": 2.1},
                "engine": {"name": "Lycoming AEIO-540", "hp": 300, "derate": 0.025},
                "g_limits": [
                    {"category": "aerobatic", "config": "clean", "positive": 6.0, "negative": -3.0},
                    {"category": "aerobatic", "config": "takeoff", "positive": 6.0, "negative": -3.0},
                    {"category": "aerobatic", "config": "landing", "positive": 6.0, "negative": -3.0},
                ],
                "stall_speeds": [
                    {"config": "clean", "weight": 1650, "speed": 61},
                    {"config": "clean", "weight": 1400, "speed": 56},
                    {"config": "landing", "weight": 1650, "speed": 54},
                ],
            },
            "default-experimental": {
                # LSA/Experimental: RV-12, CTLS, SportStar
                "aircraft_type": "single_engine",
                "gear_type": "fixed",
                "engine_count": 1,
                "wing_area": 120,
                "aspect_ratio": 8.5,
                "cd0": 0.025,
                "e": 0.82,
                "t_static": 2.5,
                "vmax": 138,
                "empty_weight": 750,
                "max_weight": 1320,
                "seats": 2,
                "fuel_capacity": 24,
                "fuel_weight": 6.0,
                "vne": 138,
                "vno": 108,
                "best_glide": 70,
                "glide_ratio": 11.0,
                "ceiling": 12000,
                "arcs": {"white": [37, 80], "green": [45, 108], "yellow": [108, 138], "red": 138},
                "vfe": {"takeoff": 90, "landing": 80},
                "clmax": {"clean": 1.45, "takeoff": 1.75, "landing": 2.05},
                "engine": {"name": "Rotax 912 ULS", "hp": 100, "derate": 0.03},
                "g_limits": [
                    {"category": "normal", "config": "clean", "positive": 4.0, "negative": -2.0},
                    {"category": "normal", "config": "takeoff", "positive": 4.0, "negative": -2.0},
                    {"category": "normal", "config": "landing", "positive": 4.0, "negative": -2.0},
                ],
                "stall_speeds": [
                    {"config": "clean", "weight": 1320, "speed": 45},
                    {"config": "takeoff", "weight": 1320, "speed": 41},
                    {"config": "landing", "weight": 1320, "speed": 37},
                ],
            },
        }

        if triggered not in defaults:
            raise PreventUpdate

        d = defaults[triggered]
        arcs = d["arcs"]
        clmax = d["clmax"]
        vfe = d["vfe"]
        eng = d["engine"]

        # Build engine options
        engine_options = [{
            "name": eng["name"],
            "horsepower": eng["hp"],
            "power_curve_sea_level": eng["hp"],
            "power_curve_derate": eng["derate"]
        }]

        # OEI data for multi-engine
        oei_data = d.get("oei", [])

        return (
            # Basic info
            d["aircraft_type"],
            d["gear_type"],
            d["engine_count"],
            # Aerodynamics
            d["wing_area"],
            d["aspect_ratio"],
            d["cd0"],
            d["e"],
            d["t_static"],
            d["vmax"],
            # Weights
            d["empty_weight"],
            d["max_weight"],
            d["seats"],
            d["fuel_capacity"],
            d["fuel_weight"],
            # Speeds
            d["vne"],
            d["vno"],
            d["best_glide"],
            d["glide_ratio"],
            d["ceiling"],
            # Arcs
            arcs["white"][0],
            arcs["white"][1],
            arcs["green"][0],
            arcs["green"][1],
            arcs["yellow"][0],
            arcs["yellow"][1],
            arcs["red"],
            # Flaps
            vfe["takeoff"],
            vfe["landing"],
            clmax["clean"],
            clmax["takeoff"],
            clmax["landing"],
            # Stores
            engine_options,
            d["g_limits"],
            d["stall_speeds"],
            oei_data,
        )

    # Hide multi-engine sections for single-engine aircraft
    @app.callback(
        Output("multi-engine-sections", "style"),
        Input("aircraft-type", "value"),
        prevent_initial_call=True
    )
    def toggle_multi_engine_sections(aircraft_type):
        if aircraft_type == "multi_engine":
            return {"display": "block"}
        else:
            return {"display": "none"}

    # Phase 1b: sync_units_toggle + expand_collapse_all moved to
    # callbacks/ui_toggles.py

    # ---- G LIMITS ----

    # import copy  # hoisted to module top in Phase 1d
    # from dash import ctx  # hoisted to module top in Phase 1d

    # === G LIMITS SECTION ===

    @app.callback(
        Output("stored-g-limits", "data", allow_duplicate=True),
        Input("add-g-limit", "n_clicks"),
        State("stored-g-limits", "data"),
        prevent_initial_call=True
    )
    def add_g_limit(n_clicks, current_data):
        if current_data is None:
            current_data = []
        updated = copy.deepcopy(current_data)
        updated.append({"category": "normal", "config": "clean", "g_value": None})
        return updated

    @app.callback(
        Output("g-limits-container", "children", allow_duplicate=True),
        Input("stored-g-limits", "data"),
        prevent_initial_call=True
    )
    def render_g_limits(g_limits):
        if not g_limits:
            return []

        return [
            html.Div([
                dcc.Dropdown(
                    id={"type": "g-category", "index": idx},
                    options=[
                        {"label": "Normal", "value": "normal"},
                        {"label": "Utility", "value": "utility"},
                        {"label": "Aerobatic", "value": "aerobatic"}
                    ],
                    value=item.get("category", "normal"),
                    style={"width": "120px", "marginRight": "10px"}
                ),
                dcc.Dropdown(
                    id={"type": "g-config", "index": idx},
                    options=[
                        {"label": "Clean/Up", "value": "clean"},
                        {"label": "TO/APP/10-20°", "value": "takeoff"},
                        {"label": "LDG/FULL/30-40°", "value": "landing"},
                    ],
                    value=item.get("config", "clean"),
                    style={"width": "200px", "marginRight": "10px"}
                ),
                dcc.Input(
                    id={"type": "g-positive", "index": idx},
                    value=item.get("positive", ""),
                    type="number",
                    placeholder="+G",
                    style={"width": "80px", "marginRight": "5px"}
                ),
                dcc.Input(
                    id={"type": "g-negative", "index": idx},
                    value=item.get("negative", ""),
                    type="number",
                    placeholder="-G",
                    style={"width": "80px", "marginRight": "5px"}
                ),
                html.Button("×", id={"type": "remove-g-limit", "index": idx}, n_clicks=0)
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px"})
            for idx, item in enumerate(g_limits)
        ]

    @app.callback(
        Output("stored-g-limits", "data", allow_duplicate=True),
        Input({"type": "g-category", "index": ALL}, "value"),
        Input({"type": "g-config", "index": ALL}, "value"),
        Input({"type": "g-positive", "index": ALL}, "value"),
        Input({"type": "g-negative", "index": ALL}, "value"),
        Input({"type": "remove-g-limit", "index": ALL}, "n_clicks"),
        State("stored-g-limits", "data"),
        prevent_initial_call=True
    )
    def update_or_remove_g_limits(categories, configs, positives, negatives, remove_clicks, current_data):
        triggered = ctx.triggered_id

        if current_data is None:
            return []

        # Handle delete
        if isinstance(triggered, dict) and triggered.get("type") == "remove-g-limit":
            idx = triggered["index"]
            if 0 <= idx < len(current_data):
                return current_data[:idx] + current_data[idx + 1:]

        # Handle edit
        if not all(len(lst) == len(current_data) for lst in [categories, configs, positives, negatives]):
            raise PreventUpdate

        return [
            {
                "category": cat,
                "config": cfg,
                "positive": pos,
                "negative": neg
            }
            for cat, cfg, pos, neg in zip(categories, configs, positives, negatives)
        ]

    # === STALL SPEEDS ===

    @app.callback(
        Output("stored-stall-speeds", "data", allow_duplicate=True),
        Input("add-stall-speed", "n_clicks"),
        State("stored-stall-speeds", "data"),
        prevent_initial_call=True
    )
    def add_stall_speed(n_clicks, current_data):
        if current_data is None:
            current_data = []
        updated = copy.deepcopy(current_data)
        updated.append({
            "config": "clean",
            "gear": "up",
            "weight": None,
            "speed": None
        })
        return updated

    @app.callback(
        Output("stall-speeds-container", "children", allow_duplicate=True),
        Input("stored-stall-speeds", "data"),
        prevent_initial_call=True
    )
    def render_stall_speeds(data):
        if data is None:
            raise PreventUpdate

        config_options = [
            {"label": "Clean/Up", "value": "clean"},
            {"label": "TO/APP/10-20°", "value": "takeoff"},
            {"label": "LDG/FULL/30-40°", "value": "landing"},
        ]
        gear_options = [
            {"label": "Gear Up", "value": "up"},
            {"label": "Gear Down", "value": "down"},
        ]

        return [
            html.Div([
                html.Div([
                    dcc.Dropdown(
                        id={"type": "stall-config", "index": idx},
                        options=config_options,
                        value=item.get("config", "clean"),
                        placeholder="Config",
                        style={"width": "200px", "marginRight": "10px"}
                    )
                ], style={"display": "inline-block"}),

                html.Div([
                    dcc.Dropdown(
                        id={"type": "stall-gear", "index": idx},
                        options=gear_options,
                        value=item.get("gear", "up"),
                        placeholder="Gear",
                        style={"width": "130px", "marginRight": "10px"}
                    )
                ], style={"display": "inline-block"}),

                html.Div([
                    dcc.Input(
                        id={"type": "stall-weight", "index": idx},
                        value=item.get("weight", ""),
                        type="number",
                        placeholder="Weight",
                        style={"width": "100px", "marginRight": "10px"}
                    )
                ], style={"display": "inline-block"}),

                html.Div([
                    dcc.Input(
                        id={"type": "stall-speed", "index": idx},
                        value=item.get("speed", ""),
                        type="number",
                        placeholder="Stall Speed",
                        style={"width": "100px", "marginRight": "10px"}
                    )
                ], style={"display": "inline-block"}),

                html.Div([
                    html.Button("×", id={"type": "remove-stall-speed", "index": idx}, n_clicks=0)
                ], style={"display": "inline-block"})
            ], style={"marginBottom": "10px", "display": "flex", "flexWrap": "nowrap", "alignItems": "center"})
            for idx, item in enumerate(data)
        ]

    @app.callback(
        Output("stored-stall-speeds", "data", allow_duplicate=True),
        Input({"type": "stall-config", "index": ALL}, "value"),
        Input({"type": "stall-gear", "index": ALL}, "value"),
        Input({"type": "stall-weight", "index": ALL}, "value"),
        Input({"type": "stall-speed", "index": ALL}, "value"),
        Input({"type": "remove-stall-speed", "index": ALL}, "n_clicks"),
        State("stored-stall-speeds", "data"),
        prevent_initial_call=True
    )
    def update_or_remove_stall(configs, gears, weights, speeds, remove_clicks, current_data):
        triggered = ctx.triggered_id
        if current_data is None:
            return []

        if isinstance(triggered, dict) and triggered.get("type") == "remove-stall-speed":
            idx = triggered["index"]
            if 0 <= idx < len(current_data):
                return current_data[:idx] + current_data[idx + 1:]

        if not all(len(x) == len(current_data) for x in [configs, gears, weights, speeds]):
            raise PreventUpdate

        return [
            {"config": c, "gear": g, "weight": w, "speed": s}
            for c, g, w, s in zip(configs, gears, weights, speeds)
        ]

    # === SINGLE ENGINE LIMITS ===

    @app.callback(
        Output("stored-single-engine-limits", "data", allow_duplicate=True),
        Input("add-single-engine-limit", "n_clicks"),
        State("stored-single-engine-limits", "data"),
        prevent_initial_call=True
    )
    def add_single_engine_limit(n_clicks, current_data):
        if current_data is None:
            current_data = []
        new_data = copy.deepcopy(current_data)
        new_data.append({
            "limit_type": "Vmca",
            "value": None,
            "flap_config": "clean",
            "gear_config": "up"
        })
        return new_data

    @app.callback(
        Output("single-engine-limits-container", "children", allow_duplicate=True),
        Input("stored-single-engine-limits", "data"),
        prevent_initial_call=True
    )
    def render_single_engine_limits(data):
        if data is None:
            raise PreventUpdate

        type_options = [
            {"label": "Vmca", "value": "Vmca"},
            {"label": "Vyse", "value": "Vyse"},
            {"label": "Vxse", "value": "Vxse"},
        ]
        flap_options = [
            {"label": "Clean/Up", "value": "clean"},
            {"label": "TO/APP/10-20°", "value": "takeoff"},
            {"label": "LDG/FULL/30-40°", "value": "landing"},
        ]
        gear_options = [
            {"label": "Up", "value": "up"},
            {"label": "Down", "value": "down"},
        ]

        return [
            html.Div([
                dcc.Dropdown(
                    id={"type": "se-limit-type", "index": idx},
                    options=type_options,
                    value=item.get("limit_type", "Vmca"),
                    style={"width": "120px", "marginRight": "10px"}
                ),

                dcc.Dropdown(
                    id={"type": "se-limit-flap", "index": idx},
                    options=flap_options,
                    value=item.get("flap_config", "clean"),
                    style={"width": "200px", "marginRight": "10px"}
                ),
                dcc.Dropdown(
                    id={"type": "se-limit-gear", "index": idx},
                    options=gear_options,
                    value=item.get("gear_config", "up"),
                    style={"width": "100px", "marginRight": "10px"}
                ),
                dcc.Input(
                    id={"type": "se-limit-value", "index": idx},
                    value=item.get("value", ""),
                    type="number",
                    placeholder="KIAS",
                    style={"width": "100px", "marginRight": "10px"}
                ),
                html.Button("×", id={"type": "remove-se-limit", "index": idx}, n_clicks=0)
            ], style={"marginBottom": "10px", "display": "flex", "alignItems": "center"})
            for idx, item in enumerate(data)
        ]
    @app.callback(
        Output("stored-single-engine-limits", "data", allow_duplicate=True),
        Input({"type": "se-limit-type", "index": ALL}, "value"),
        Input({"type": "se-limit-value", "index": ALL}, "value"),
        Input({"type": "se-limit-flap", "index": ALL}, "value"),
        Input({"type": "se-limit-gear", "index": ALL}, "value"),
        Input({"type": "remove-se-limit", "index": ALL}, "n_clicks"),
        State("stored-single-engine-limits", "data"),
        prevent_initial_call=True
    )
    def update_or_remove_se_limits(types, values, flaps, gears, remove_clicks, current_data):
        triggered = ctx.triggered_id
        if current_data is None:
            return []

        if isinstance(triggered, dict) and triggered.get("type") == "remove-se-limit":
            idx = triggered.get("index")
            if 0 <= idx < len(current_data):
                return current_data[:idx] + current_data[idx + 1:]

        if not all(len(x) == len(current_data) for x in [types, values, flaps, gears]):
            raise PreventUpdate

        return [
            {
                "limit_type": t,
                "value": v,
                "flap_config": f,
                "gear_config": g
            }
            for t, v, f, g in zip(types, values, flaps, gears)
        ]
    #----- OEI Performance----

    @app.callback(
        Output("stored-oei-performance", "data", allow_duplicate=True),
        Input("add-oei-performance", "n_clicks"),
        State("stored-oei-performance", "data"),
        prevent_initial_call=True
    )
    def add_oei_entry(n_clicks, current_data):
        if current_data is None:
            current_data = []
        new_data = copy.deepcopy(current_data)
        new_data.append({
            "config": "clean_up",
            "prop_condition": "normal",
            "max_power_fraction": None,
        })
        return new_data

    @app.callback(
        Output("oei-performance-container", "children", allow_duplicate=True),
        Input("stored-oei-performance", "data"),
        prevent_initial_call=True
    )
    def render_oei_entries(data):
        if not data:
            return []

        prop_options = [
            {"label": "Feathered", "value": "Feathered"},
            {"label": "Windmilling", "value": "windmilling"},
            {"label": "Stationary", "value": "stationary"}
        ]

        config_options = [
            {"label": "Clean / Up", "value": "clean_up"},
            {"label": "Landing / Down", "value": "landing_down"}
        ]

        return [
            html.Div([
                dcc.Dropdown(
                    id={"type": "oei-config", "index": idx},
                    options=config_options,
                    value=item.get("config", "clean_up"),
                    style={"width": "150px", "marginRight": "10px"}
                ),
                dcc.Dropdown(
                    id={"type": "oei-prop", "index": idx},
                    options=prop_options,
                    value=item.get("prop_condition", "normal"),
                    style={"width": "150px", "marginRight": "10px"}
                ),
                dcc.Input(
                    id={"type": "oei-power", "index": idx},
                    type="number",
                    value=item.get("max_power_fraction"),
                    placeholder="Power Fraction",
                    step=0.01,
                    style={"width": "140px", "marginRight": "10px"}
                ),
                html.Button("×", id={"type": "remove-oei", "index": idx}, n_clicks=0)
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "10px"})
            for idx, item in enumerate(data)
        ]

    @app.callback(
        Output("stored-oei-performance", "data", allow_duplicate=True),
        Input({"type": "oei-config", "index": ALL}, "value"),
        Input({"type": "oei-prop", "index": ALL}, "value"),
        Input({"type": "oei-power", "index": ALL}, "value"),
        Input({"type": "oei-efficiency", "index": ALL}, "value"),
        Input({"type": "remove-oei", "index": ALL}, "n_clicks"),
        State("stored-oei-performance", "data"),
        prevent_initial_call=True
    )
    def update_oei_entries(configs, props, powers, effs, remove_clicks, current_data):
        triggered = ctx.triggered_id
        if current_data is None:
            return []

        # Deletion case
        if isinstance(triggered, dict) and triggered.get("type") == "remove-oei":
            idx = triggered["index"]
            if 0 <= idx < len(current_data):
                return current_data[:idx] + current_data[idx + 1:]

        # Edit case
        if not all(len(x) == len(current_data) for x in [configs, props, powers, effs]):
            raise PreventUpdate

        return [
            {
                "config": c,
                "prop_condition": p,
                "max_power_fraction": f,
            }
            for c, p, f, in zip(configs, props, powers)
        ]

    # === ENGINE OPTIONS ===

    @app.callback(
        Output("stored-engine-options", "data", allow_duplicate=True),
        Input("add-engine-option", "n_clicks"),
        State("stored-engine-options", "data"),
        prevent_initial_call=True
    )
    def add_engine_option(n_clicks, current_engines):
        if current_engines is None:
            current_engines = []
        new_data = copy.deepcopy(current_engines)
        new_data.append({
            "name": "",
            "horsepower": None,
            "power_curve_sea_level": None,
            "power_curve_derate": 0.03,
        })
        return new_data

    @app.callback(
        Output("engine-options-container", "children", allow_duplicate=True),
        Input("stored-engine-options", "data"),
        prevent_initial_call=True
    )
    def render_engine_options(engine_data):
        if engine_data is None:
            raise PreventUpdate

        return [
            html.Div([
                dcc.Input(
                    id={"type": "engine-name", "index": idx},
                    value=item.get("name", ""),
                    type="text",
                    placeholder="Engine Name",
                    style={"width": "180px", "marginRight": "5px"}
                ),
                dcc.Input(
                    id={"type": "engine-hp", "index": idx},
                    value=item.get("horsepower", 0),
                    type="number",
                    placeholder="Horsepower",
                    style={"width": "100px", "marginRight": "5px"}
                ),
                dcc.Input(
                    id={"type": "power-curve-sea-level", "index": idx},
                    value=item.get("power_curve_sea_level", ""),
                    type="number",
                    placeholder="Sea Level HP",
                    style={"width": "120px", "marginRight": "5px"}
                ),
                dcc.Input(
                    id={"type": "power-curve-derate", "index": idx},
                    value=item.get("power_curve_derate", 0.03),
                    type="number",
                    step="0.001",
                    placeholder="Derate / 1000 ft",
                    style={"width": "130px", "marginRight": "5px"}
                ),
                html.Button("×", id={"type": "remove-engine", "index": idx}, n_clicks=0)
            ], style={"marginBottom": "12px", "display": "flex", "flexWrap": "wrap"})
            for idx, item in enumerate(engine_data)
        ]

    @app.callback(
        Output("stored-engine-options", "data", allow_duplicate=True),
        Input({"type": "engine-name", "index": ALL}, "value"),
        Input({"type": "engine-hp", "index": ALL}, "value"),
        Input({"type": "power-curve-sea-level", "index": ALL}, "value"),
        Input({"type": "power-curve-derate", "index": ALL}, "value"),
        Input({"type": "remove-engine", "index": ALL}, "n_clicks"),
        State("stored-engine-options", "data"),
        prevent_initial_call=True
    )
    def update_or_remove_engines(names, hps, sea_levels, derates, remove_clicks, current_data):
        triggered = ctx.triggered_id
        if current_data is None:
            return []

        if isinstance(triggered, dict) and triggered.get("type") == "remove-engine":
            idx = triggered.get("index")
            if 0 <= idx < len(current_data):
                return current_data[:idx] + current_data[idx + 1:]

        if not all(len(x) == len(current_data) for x in [names, hps, sea_levels, derates]):
            raise PreventUpdate

        return [
            {
                "name": n,
                "horsepower": hp,
                "power_curve_sea_level": sea,
                "power_curve_derate": derate
            }
            for n, hp, sea, derate in zip(names, hps, sea_levels, derates)
        ]


    @app.callback(
        [
            Output("aircraft-name", "value", allow_duplicate=True),
            Output("aircraft-type", "value", allow_duplicate=True),
            Output("gear-type", "value", allow_duplicate=True),
            Output("engine-count", "value", allow_duplicate=True),
            Output("wing-area", "value", allow_duplicate=True),
            Output("aspect-ratio", "value", allow_duplicate=True),
            Output("cd0", "value", allow_duplicate=True),
            Output("oswald-efficiency", "value", allow_duplicate=True),
            Output("stored-flap-configs", "data", allow_duplicate=True),
            Output("stored-g-limits", "data", allow_duplicate=True),
            Output("g-limits-container", "children", allow_duplicate=True),
            Output("stored-stall-speeds", "data", allow_duplicate=True),
            Output("stall-speeds-container", "children", allow_duplicate=True),
            Output("stored-single-engine-limits", "data", allow_duplicate=True),
            Output("stored-engine-options", "data", allow_duplicate=True),
            Output("engine-options-container", "children", allow_duplicate=True),
            Output("empty-weight", "value", allow_duplicate=True),
            Output("max-weight", "value", allow_duplicate=True),
            Output("best-glide", "value", allow_duplicate=True),
            Output("best-glide-ratio", "value", allow_duplicate=True),
            Output("seats", "value", allow_duplicate=True),
            Output("cg-fwd", "value", allow_duplicate=True),
            Output("cg-aft", "value", allow_duplicate=True),
            Output({"type": "vfe-input", "config": "takeoff"}, "value", allow_duplicate=True),
            Output({"type": "vfe-input", "config": "landing"}, "value", allow_duplicate=True),
            Output({"type": "clmax-input", "config": "clean"}, "value", allow_duplicate=True),
            Output({"type": "clmax-input", "config": "takeoff"}, "value", allow_duplicate=True),
            Output({"type": "clmax-input", "config": "landing"}, "value", allow_duplicate=True),
            Output("fuel-capacity-gal", "value", allow_duplicate=True),
            Output("fuel-weight-per-gal", "value", allow_duplicate=True),
            Output("arc-white-bottom", "value", allow_duplicate=True),
            Output("arc-white-top", "value", allow_duplicate=True),
            Output("arc-green-bottom", "value", allow_duplicate=True),
            Output("arc-green-top", "value", allow_duplicate=True),
            Output("arc-yellow-bottom", "value", allow_duplicate=True),
            Output("arc-yellow-top", "value", allow_duplicate=True),
            Output("arc-red", "value", allow_duplicate=True),
            Output("prop-static-factor", "value", allow_duplicate=True),
            Output("prop-vmax-kts", "value", allow_duplicate=True),
            Output("stored-oei-performance", "data", allow_duplicate=True),
            Output("max-altitude", "value", allow_duplicate=True),
            Output("vne", "value", allow_duplicate=True),
            Output("vno", "value", allow_duplicate=True),
            Output("search-result", "children", allow_duplicate=True),
        ],
        Input("new-aircraft-button", "n_clicks"),
        prevent_initial_call=True
    )
    def clear_all_fields(n_clicks):
        return (
            "",  # aircraft-name
            "",  # aircraft-type
            "fixed",  # gear-type
            1,   # engine-count
            None,  # wing-area
            None,  # aspect-ratio
            None,  # cd0
            None,  # oswald-efficiency
            [],    # stored-flap-configs
            [],    # stored-g-limits
            [],    # g-limits-container (children)
            [],    # stored-stall-speeds
            [],    # stall-speeds-container (children)
            [],    # stored-single-engine-limits
            [],    # stored-engine-options
            [],    # engine-options-container (children)
            None,  # empty-weight
            None,  # max-weight
            None,  # best-glide
            None,  # best-glide-ratio
            None,  # seats
            None,  # cg-fwd
            None,  # cg-aft
            None,  # vfe takeoff
            None,  # vfe landing
            None,  # clmax clean
            None,  # clmax takeoff
            None,  # clmax landing
            None,  # fuel-capacity-gal
            None,  # fuel-weight-per-gal
            None,  # arc-white-bottom
            None,  # arc-white-top
            None,  # arc-green-bottom
            None,  # arc-green-top
            None,  # arc-yellow-bottom
            None,  # arc-yellow-top
            None,  # arc-red
            None,  # prop-static-factor
            None,  # prop-vmax-kts
            [],    # stored-oei-performance
            None,  # max-altitude
            None,  # vne
            None,  # vno
            "⬜ New aircraft ready"  # search-result.children
        )


    @app.callback(
        Output("vne", "value", allow_duplicate=True),
        Output("vno", "value", allow_duplicate=True),
        Output({"type": "vfe-input", "config": "takeoff"}, "value", allow_duplicate=True),
        Output({"type": "vfe-input", "config": "landing"}, "value", allow_duplicate=True),
        Output("arc-white-bottom", "value", allow_duplicate=True),
        Output("arc-white-top", "value", allow_duplicate=True),
        Output("arc-green-bottom", "value", allow_duplicate=True),
        Output("arc-green-top", "value", allow_duplicate=True),
        Output("arc-yellow-bottom", "value", allow_duplicate=True),
        Output("arc-yellow-top", "value", allow_duplicate=True),
        Output("arc-red", "value", allow_duplicate=True),
        Output("stored-stall-speeds", "data", allow_duplicate=True),
        Output("stored-single-engine-limits", "data", allow_duplicate=True),
        Input("units-toggle", "value"),
        State("vne", "value"),
        State("vno", "value"),
        State({"type": "vfe-input", "config": "takeoff"}, "value"),
        State({"type": "vfe-input", "config": "landing"}, "value"),
        State("arc-white-bottom", "value"),
        State("arc-white-top", "value"),
        State("arc-green-bottom", "value"),
        State("arc-green-top", "value"),
        State("arc-yellow-bottom", "value"),
        State("arc-yellow-top", "value"),
        State("arc-red", "value"),
        State("stored-stall-speeds", "data"),
        State("stored-single-engine-limits", "data"),
        prevent_initial_call=True
    )
    def convert_units_toggle(units,
        vne, vno, vfe_to, vfe_ldg,
        arc_white_btm, arc_white_top,
        arc_green_btm, arc_green_top,
        arc_yellow_btm, arc_yellow_top,
        arc_red,
        stall_data, se_limits
    ):
        # Prevent meaningless toggles
        if units not in ("MPH", "KIAS"):
            raise PreventUpdate

        # Conversion functions
        def to_mph(val): return round(val * KTS_TO_MPH, 1) if val is not None else None
        def to_kias(val): return round(val / KTS_TO_MPH, 1) if val is not None else None
        convert = to_mph if units == "MPH" else to_kias

        # Convert airspeeds
        vne_new = convert(vne)
        vno_new = convert(vno)
        vfe_to_new = convert(vfe_to)
        vfe_ldg_new = convert(vfe_ldg)
        arc_white_btm_new = convert(arc_white_btm)
        arc_white_top_new = convert(arc_white_top)
        arc_green_btm_new = convert(arc_green_btm)
        arc_green_top_new = convert(arc_green_top)
        arc_yellow_btm_new = convert(arc_yellow_btm)
        arc_yellow_top_new = convert(arc_yellow_top)
        arc_red_new = convert(arc_red)

        # Stall speeds
        updated_stalls = []
        for item in stall_data or []:
            item = item.copy()
            if item.get("speed") is not None:
                item["speed"] = convert(item["speed"])
            updated_stalls.append(item)

        # Single engine limits
        updated_se = []
        for entry in se_limits or []:
            entry = entry.copy()
            if entry.get("limit_type") in ("Vmca", "Vyse", "Vxse"):
                if entry.get("value") is not None:
                    entry["value"] = convert(entry["value"])
            updated_se.append(entry)

        return (
            vne_new, vno_new,
            vfe_to_new, vfe_ldg_new,
            arc_white_btm_new, arc_white_top_new,
            arc_green_btm_new, arc_green_top_new,
            arc_yellow_btm_new, arc_yellow_top_new,
            arc_red_new,
            updated_stalls,
            updated_se
        )


    def _build_single_engine_limits(se_limits, best_glide, best_glide_ratio):
        """
        Build the single_engine_limits dict with proper nesting for multi-engine aircraft.

        Input se_limits format (list of dicts):
            {"limit_type": "Vmca", "flap_config": "clean", "gear_config": "up", "value": 56}

        Output format (matching JSON schema):
            {
                "Vmca": {"clean_up": 56, "takeoff_up": 56, ...},
                "Vyse": {...},
                "Vxse": {...},
                "best_glide": 106,
                "best_glide_ratio": 9.5
            }
        """
        result = {}

        # Group by limit_type with config keys
        for s in (se_limits or []):
            limit_type = s.get("limit_type")
            if not limit_type:
                continue

            flap = s.get("flap_config", "clean")
            gear = s.get("gear_config", "up")
            value = s.get("value")

            # Build config key like "clean_up", "takeoff_down", "landing_down"
            config_key = f"{flap}_{gear}"

            if limit_type not in result:
                result[limit_type] = {}

            result[limit_type][config_key] = value

        # Add best glide info
        if best_glide is not None:
            result["best_glide"] = best_glide
        if best_glide_ratio is not None:
            result["best_glide_ratio"] = best_glide_ratio

        return result


    @app.callback(
        [
            Output("save-status", "children", allow_duplicate=True),
            Output("aircraft-data-store", "data", allow_duplicate=True),
            Output("last-saved-aircraft", "data", allow_duplicate=True),
            Output("download-aircraft", "data", allow_duplicate=True),
        ],
        Input("save-aircraft-button", "n_clicks"),
        State("aircraft-data-store", "data"),
        State("aircraft-name", "value"),
        State("wing-area", "value"),
        State("aspect-ratio", "value"),
        State("cd0", "value"),
        State("oswald-efficiency", "value"),
        State("stored-flap-configs", "data"),
        State("stored-g-limits", "data"),
        State("stored-stall-speeds", "data"),
        State("stored-single-engine-limits", "data"),
        State("stored-engine-options", "data"),
        State("units-toggle", "value"),
        State("empty-weight", "value"),
        State("max-weight", "value"),
        State("seats", "value"),
        State("cg-fwd", "value"),
        State("cg-aft", "value"),
        State("fuel-capacity-gal", "value"),
        State("fuel-weight-per-gal", "value"),
        State("arc-white-bottom", "value"),
        State("arc-white-top", "value"),
        State("arc-green-bottom", "value"),
        State("arc-green-top", "value"),
        State("arc-yellow-bottom", "value"),
        State("arc-yellow-top", "value"),
        State("arc-red", "value"),
        State("prop-static-factor", "value"),
        State("prop-vmax-kts", "value"),
        State("best-glide", "value"),
        State("best-glide-ratio", "value"),
        State("aircraft-type", "value"),
        State("engine-count", "value"),
        State("vne", "value"),
        State("vno", "value"),
        State({"type": "vfe-input", "config": "takeoff"}, "value"),
        State({"type": "vfe-input", "config": "landing"}, "value"),
        State({"type": "clmax-input", "config": "clean"}, "value"),
        State({"type": "clmax-input", "config": "takeoff"}, "value"),
        State({"type": "clmax-input", "config": "landing"}, "value"),
        State("max-altitude", "value"),
        State("gear-type", "value"),
        State("stored-oei-performance", "data"),
        prevent_initial_call=True
    )
    def save_aircraft_to_file(
        n_clicks,
        current_data,
        name, wing_area, ar, cd0, e,
        flaps, g_limits, stall_speeds, se_limits, engines,
        units, empty_weight, max_weight, seats, cg_fwd, cg_aft, fuel_capacity, fuel_weight,
        white_btm, white_top, green_btm, green_top, yellow_btm, yellow_top, red,
        t_static, v_max_kts, best_glide, best_glide_ratio, aircraft_type, engine_count, vne, vno,
        vfe_takeoff, vfe_landing,
        clmax_clean, clmax_takeoff, clmax_landing, max_altitude, gear_type, oei_performance
    ):
        # Phase 5T: pre-save sanity gate. Refuses save on geometry violations
        # that would silently produce bad EM diagrams. Surface as a single
        # error line in the search-result slot. Layered before the existing
        # path so save_aircraft never sees obviously invalid input.
        critical_errors: list[str] = []
        if not name:
            critical_errors.append("Aircraft name is required.")
        try:
            if vne is not None and vno is not None and float(vne) <= float(vno):
                critical_errors.append(f"Vne ({vne}) must exceed Vno ({vno}).")
        except (TypeError, ValueError):
            pass
        try:
            if empty_weight is not None and max_weight is not None and float(empty_weight) >= float(max_weight):
                critical_errors.append(f"Empty weight ({empty_weight}) must be less than max weight ({max_weight}).")
        except (TypeError, ValueError):
            pass
        try:
            if cd0 is not None and (float(cd0) <= 0 or float(cd0) > 0.15):
                critical_errors.append(f"CD0 ({cd0}) is outside the expected [0, 0.15] range.")
        except (TypeError, ValueError):
            pass
        try:
            if e is not None and (float(e) <= 0 or float(e) > 1.0):
                critical_errors.append(f"Oswald efficiency e ({e}) must be in (0, 1].")
        except (TypeError, ValueError):
            pass
        try:
            if ar is not None and (float(ar) < 3 or float(ar) > 20):
                critical_errors.append(f"Aspect ratio ({ar}) is outside the typical [3, 20] range.")
        except (TypeError, ValueError):
            pass
        if critical_errors:
            return (
                "Save blocked: " + "  ·  ".join(critical_errors),
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )

        # Track aircraft save/creation
        log_feature('aircraft_save', {
            'aircraft': name,
            'type': aircraft_type,
            'engine_count': engine_count
        })

        try:
            def convert_speed(val):
                return round(val / KTS_TO_MPH, 1) if units == "MPH" and isinstance(val, (int, float)) else val

            # --- Convert stall + SE limits ---
            converted_stalls = [
                {
                    "config": s["config"],
                    "gear": s["gear"],
                    "weight": s["weight"],
                    "speed": convert_speed(s["speed"])
                } for s in (stall_speeds or [])
            ]

            converted_se_limits = [
                {
                    "limit_type": s["limit_type"],
                    "flap_config": s["flap_config"],
                    "gear_config": s["gear_config"],
                    "value": convert_speed(s["value"])
                } for s in (se_limits or [])
            ]

            # --- Engines with OEI Performance ---
            engine_dict = {}
            if engines:
                for eng in engines:
                    eng_name = eng.get("name", "Unnamed Engine")
                    eng_data = {
                        "horsepower": eng.get("horsepower"),
                        "power_curve": {
                            "sea_level_max": eng.get("power_curve_sea_level"),
                            "derate_per_1000ft": eng.get("power_curve_derate"),
                        },
                    }

                    # Build OEI performance structure for this engine
                    # OEI data is stored flat with config (e.g. "clean_up") and prop_condition
                    oei_struct = {}
                    for oei in (oei_performance or []):
                        # Handle both "config" and "config_key" for compatibility
                        config_key = oei.get("config") or oei.get("config_key", "clean_up")
                        prop_cond = oei.get("prop_condition", "feathered").lower()

                        if config_key not in oei_struct:
                            oei_struct[config_key] = {}

                        oei_struct[config_key][prop_cond] = {
                            "max_power_fraction": oei.get("max_power_fraction"),
                        }

                    if oei_struct:
                        eng_data["oei_performance"] = oei_struct

                    engine_dict[eng_name] = eng_data

            # --- G limits ---
            g_structured = {}
            for g in (g_limits or []):
                cat = g.get("category")
                cfg = g.get("config")
                pos = g.get("positive")
                neg = g.get("negative")

                # Default negative G to 0 if not specified
                if neg is None:
                    neg = 0

                if cat and cfg:
                    g_structured.setdefault(cat, {})[cfg] = {
                        "positive": pos,
                        "negative": neg,
                    }

            # --- Stall structured ---
            stall_structured = {}
            for s in converted_stalls:
                cfg = s["config"]
                if cfg not in stall_structured:
                    stall_structured[cfg] = {"weights": [], "speeds": []}
                stall_structured[cfg]["weights"].append(s["weight"])
                stall_structured[cfg]["speeds"].append(s["speed"])

            # --- Flap names ---
            flap_names = [f["name"] for f in (flaps or []) if isinstance(f, dict) and f.get("name")]
            if not flap_names:
                flap_names = ["clean", "takeoff", "landing"]

            # --- Vfe dict (using the dedicated Vfe fields you added) ---
            arcs = {
                "white": [convert_speed(white_btm), convert_speed(white_top)],
                "green": [convert_speed(green_btm), convert_speed(green_top)],
                "yellow": [convert_speed(yellow_btm), convert_speed(yellow_top)],
                "red": convert_speed(red),
            }

            vfe_dict = {}
            if vfe_takeoff is not None:
                vfe_dict["takeoff"] = convert_speed(vfe_takeoff)
            if vfe_landing is not None:
                vfe_dict["landing"] = convert_speed(vfe_landing)

            # --- CLmax dict ---
            clmax_dict = {}
            if clmax_clean is not None:
                clmax_dict["clean"] = clmax_clean
            if clmax_takeoff is not None:
                clmax_dict["takeoff"] = clmax_takeoff
            if clmax_landing is not None:
                clmax_dict["landing"] = clmax_landing

            # --- Build aircraft dict ---
            ac_dict = {
                "name": name,
                "type": aircraft_type,
                "gear_type": gear_type,
                "engine_count": engine_count,
                "wing_area": wing_area,
                "aspect_ratio": ar,
                "CD0": cd0,
                "e": e,
                "configuration_options": {"flaps": flap_names},
                "G_limits": g_structured,
                "stall_speeds": stall_structured,
                "engine_options": engine_dict,
                "max_altitude": max_altitude,
                "Vne": convert_speed(vne),
                "Vno": convert_speed(vno),
                "Vfe": vfe_dict,
                "CL_max": clmax_dict,
                "arcs": arcs,
                "empty_weight": empty_weight,
                "max_weight": max_weight,
                "single_engine_limits": _build_single_engine_limits(
                    converted_se_limits, best_glide, best_glide_ratio
                ),
                "seats": seats,
                "cg_range": [cg_fwd, cg_aft],
                "fuel_capacity_gal": fuel_capacity,
                "fuel_weight_per_gal": fuel_weight,
                "prop_thrust_decay": {
                    "T_static_factor": t_static,
                    "V_max_kts": v_max_kts,
                },
            }

            # --- Write to disk ---
            filename = name.replace(" ", "_") + ".json"
            filepath = os.path.join("aircraft_data", filename)

            if os.path.exists(filepath):
                # File already exists – do NOT overwrite, do NOT change store
                return (
                    "Save blocked: that aircraft name already exists. Pick a different name (or click Duplicate first).",
                    dash.no_update,
                    dash.no_update,
                    dash.no_update,
                )

            with open(filepath, "w") as f:
                json.dump(ac_dict, f, indent=2)

            # --- Update in-memory data store instead of reloading from folder ---
            current_data = current_data or {}
            current_data[name] = ac_dict

            return (
                f"Saved as {filename}",
                current_data,                                        # aircraft-data-store
                name,                                                # last-saved-aircraft
                dcc.send_string(json.dumps(ac_dict, indent=2), filename),  # download-aircraft
            )

        except Exception as e:
            return (
                f"Error saving: {str(e)}",
                dash.no_update,
                dash.no_update,
                dash.no_update,
            )


    # from flask import send_from_directory  # hoisted to module top in Phase 1d

    # from dash import Output, Input, State, ctx, dcc  # hoisted to module top in Phase 1d
    # import json  # hoisted to module top in Phase 1d

    # import base64  # hoisted to module top in Phase 1d
    # import json  # hoisted to module top in Phase 1d
    # from dash import Input, Output, State  # hoisted to module top in Phase 1d
    # from dash.exceptions import PreventUpdate  # hoisted to module top in Phase 1d

    @app.callback(
        [
            Output("aircraft-data-store", "data", allow_duplicate=True),
            Output("aircraft-select", "value", allow_duplicate=True),  # correct dropdown
            Output("last-saved-aircraft", "data", allow_duplicate=True)
        ],
        Input("upload-aircraft", "contents"),
        State("upload-aircraft", "filename"),
        State("aircraft-data-store", "data"),
        prevent_initial_call=True
    )
    def load_aircraft_from_upload(contents, filename, current_data):
        if not contents or not filename:
            raise PreventUpdate

        try:
            # Decode base64-encoded JSON string
            content_type, content_string = contents.split(",")
            decoded = base64.b64decode(content_string)
            aircraft_json = json.loads(decoded.decode("utf-8"))

            # Use 'name' key from JSON if present, else fallback to filename
            name = aircraft_json.get("name") or filename.replace(".json", "").replace("_", " ").strip()

            # Inject aircraft into stored dict
            current_data = current_data or {}
            current_data[name] = aircraft_json

            # Track aircraft upload
            log_feature('aircraft_upload', {
                'aircraft': name,
                'type': aircraft_json.get('type', 'unknown'),
                'engine_count': aircraft_json.get('engine_count', 1)
            })

            dprint(f"[UPLOAD] Loaded aircraft: {name}")
            return current_data, name, name

        except Exception as e:
            dprint(f"[UPLOAD ERROR]: {e}")
            raise PreventUpdate
