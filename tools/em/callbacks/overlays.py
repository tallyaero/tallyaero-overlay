"""TallyAero EM Diagram — multi-engine overlay sync and mobile-sidebar callbacks."""

from __future__ import annotations

from dash import ctx, dcc, html
from dash.dependencies import ALL, Input, Output, State
from dash.exceptions import PreventUpdate

from core import dprint


def register(app):
    """Install every callback in this module."""
    @app.callback(
        Output("overlay-toggle", "data", allow_duplicate=True),
        Input("mobile-overlay-checklist", "value"),
        prevent_initial_call=True
    )
    def sync_mobile_overlay_to_store(checklist_value):
        """Sync mobile overlay checklist to the overlay-toggle store."""
        return checklist_value if checklist_value is not None else []

    # Phase 5AB-13: rail-collapse feature retired. The drawer is the
    # "more configure" home; the rail itself stays open.

    # Phase 5O: settings drawer open/close. Triggered by the "Configure"
    # chip in the rail; dbc.Offcanvas handles the close button + backdrop
    # click natively via its own is_open prop.
    @app.callback(
        Output("settings-drawer", "is_open"),
        Input("open-drawer-btn", "n_clicks"),
        State("settings-drawer", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_settings_drawer(n_clicks, is_open):
        return not is_open if n_clicks else is_open

    # Phase 5AF: mobile-settings-toggle now drives the offcanvas drawer that
    # replaced the old in-page collapse. Button label stays "☰" so it reads
    # as a persistent hamburger; toggling state is via the drawer's own
    # backdrop / close-button on close.
    @app.callback(
        Output("mobile-settings-drawer", "is_open"),
        Input("mobile-settings-toggle", "n_clicks"),
        State("mobile-settings-drawer", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_mobile_settings(n_clicks, is_open):
        return not bool(is_open) if n_clicks else bool(is_open)

    @app.callback(
        Output("overlay-toggle", "data"),
        Input("toggle-ps", "value"),
        Input("toggle-g", "value"),
        Input("toggle-radius", "value"),
        Input("toggle-aob", "value"),
        Input("toggle-negative-g", "value"),
        prevent_initial_call=True
    )
    def sync_overlay_switches(ps_on, g_on, radius_on, aob_on, neg_g_on):
        """Sync individual overlay switches to the overlay-toggle store."""
        selected = []
        if ps_on:
            selected.append("ps")
        if g_on:
            selected.append("g")
        if radius_on:
            selected.append("radius")
        if aob_on:
            selected.append("aob")
        if neg_g_on:
            selected.append("negative_g")
        return selected

    @app.callback(
        Output("multi-engine-toggle-options", "data"),
        Input("toggle-vmca", "value"),
        Input("toggle-vyse", "value"),
        prevent_initial_call=True
    )
    def sync_me_switches(vmca_on, vyse_on):
        """Sync multi-engine switches to the multi-engine-toggle-options store."""
        selected = []
        if vmca_on:
            selected.append("vmca")
        if vyse_on:
            selected.append("dynamic_vyse")
        return selected

