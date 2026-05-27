"""
Self-contained UI-state toggle callbacks.

These don't touch aircraft data, don't run physics, and don't depend on the
layout structure — they just route button clicks to a `dcc.Store` value or a
visibility style. Pure UI plumbing.

Migrated from app.py in Phase 1b without behavior changes.
"""

from __future__ import annotations

from dash import ctx
from dash.dependencies import Input, Output


def register(app):
    # --- Airspeed unit toggle (KIAS / MPH segmented control) ------------
    @app.callback(
        Output("unit-select", "data"),
        Output("btn-kias", "className"),
        Output("btn-mph", "className"),
        Input("btn-kias", "n_clicks"),
        Input("btn-mph", "n_clicks"),
        prevent_initial_call=True,
    )
    def toggle_airspeed_units(_kias_clicks, _mph_clicks):
        triggered = ctx.triggered_id
        if triggered == "btn-kias":
            return "KIAS", "segment-btn active", "segment-btn"
        if triggered == "btn-mph":
            return "MPH", "segment-btn", "segment-btn active"
        return "KIAS", "segment-btn active", "segment-btn"

    # --- Propeller condition toggle (feathered / stationary / windmilling)
    @app.callback(
        Output("prop-condition", "data"),
        Output("btn-feathered", "className"),
        Output("btn-stationary", "className"),
        Output("btn-windmilling", "className"),
        Input("btn-feathered", "n_clicks"),
        Input("btn-stationary", "n_clicks"),
        Input("btn-windmilling", "n_clicks"),
        prevent_initial_call=True,
    )
    def toggle_prop_condition(_feath, _stat, _wind):
        triggered = ctx.triggered_id
        if triggered == "btn-feathered":
            return "feathered", "segment-btn active", "segment-btn", "segment-btn"
        if triggered == "btn-stationary":
            return "stationary", "segment-btn", "segment-btn active", "segment-btn"
        if triggered == "btn-windmilling":
            return "windmilling", "segment-btn", "segment-btn", "segment-btn active"
        return "feathered", "segment-btn active", "segment-btn", "segment-btn"

    # --- ACS Standard: mutually exclusive radio behavior --------------
    @app.callback(
        Output({"type": "steepturn-standard", "index": 0}, "value"),
        Input({"type": "steepturn-standard", "index": 0}, "value"),
        prevent_initial_call=True,
    )
    def enforce_single_standard(current_value):
        """Only allow one ACS standard to be selected at a time."""
        if not current_value or len(current_value) <= 1:
            return current_value
        return [current_value[-1]]

    # --- ACS Standard container: visible only when Ghost Trace is on
    @app.callback(
        Output("acs-standard-container", "style"),
        Input({"type": "steepturn-ghost", "index": 0}, "value"),
        prevent_initial_call=True,
    )
    def toggle_acs_standard_visibility(ghost_value):
        """Show ACS Standard options only when Ghost Trace is enabled."""
        if ghost_value is True or (isinstance(ghost_value, list) and "on" in ghost_value):
            return {"display": "block"}
        return {"display": "none"}

    # --- Edit page: units switch syncs to the hidden Store ------------
    @app.callback(
        Output("em-units-toggle", "value"),
        Input("units-toggle-switch", "value"),
        prevent_initial_call=True,
    )
    def sync_units_toggle(switch_value):
        return "MPH" if switch_value else "KIAS"

    # --- Edit page: expand/collapse all accordions -------------------
    @app.callback(
        Output("edit-accordion", "active_item"),
        Input("expand-all-btn", "n_clicks"),
        Input("collapse-all-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def expand_collapse_all(_expand, _collapse):
        triggered = ctx.triggered_id
        all_items = ["basic", "aero", "weight", "speeds", "flaps", "glimits", "stall", "engines"]
        if triggered == "expand-all-btn":
            return all_items
        return []
