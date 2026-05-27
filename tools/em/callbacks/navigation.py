"""
Routing / navigation callbacks.

Self-contained URL-pathname callbacks. None of these touch aircraft data
or run physics. Migrated from app.py in Phase 1b without behavior changes.
"""

from __future__ import annotations

import flask
from dash import html
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate

from core import AIRCRAFT_DATA, aircraft_data
from layouts import edit_aircraft_layout, em_diagram_layout


def register(app):
    # --- "Edit / Create Aircraft" button → /edit-aircraft -------------
    # Phase 5T: also write the currently-selected aircraft into the
    # `editing-aircraft` Store so the edit page can auto-load that aircraft.
    @app.callback(
        Output("url", "pathname"),
        Output("editing-aircraft", "data"),
        Input("edit-aircraft-button", "n_clicks"),
        State("aircraft-select", "value"),
        prevent_initial_call=True,
    )
    def go_to_edit_page(n_clicks, current_aircraft):
        if not n_clicks:
            raise PreventUpdate
        return "/edit-aircraft", current_aircraft

    # --- Edit-page "Back" button → / ---------------------------------
    @app.callback(
        Output("url", "pathname", allow_duplicate=True),
        Input("back-button", "n_clicks"),
        prevent_initial_call=True,
    )
    def go_to_main_page(n_clicks):
        if n_clicks:
            return "/"
        raise PreventUpdate

    # --- On return to "/", restore the most-recently-saved aircraft --
    @app.callback(
        Output("aircraft-select", "value", allow_duplicate=True),
        Input("url", "pathname"),
        State("last-saved-aircraft", "data"),
        prevent_initial_call=True,
    )
    def load_last_saved_on_nav(path, last_saved):
        if path == "/" and last_saved:
            return last_saved
        raise PreventUpdate

    # --- Browser width sniffer (fires on initial load) ----------------
    @app.callback(
        Output("browser-width", "data"),
        Input("url", "pathname"),
    )
    def get_browser_width(_pathname):
        """Best-effort UA-string detection; client-side JS fills the real
        width into the screen-width Store. This is a coarse fallback used
        when the JS hasn't run yet."""
        try:
            return flask.request.headers.get("User-Agent")
        except Exception:
            return None
    # ─── Phase 1g additions ────────────────────────────────────────────
    @app.callback(
        Output("page-content", "children"),
        Input("url", "pathname"),
        Input("screen-width", "data")
    )
    def display_page(pathname, screen_width):
        # Gracefully handle undefined screen width
        if screen_width is None:
            screen_width = 1024  # assume desktop by default

        is_mobile = screen_width < 768

        if pathname == "/" or pathname is None:
            return em_diagram_layout(is_mobile=is_mobile)
        elif pathname == "/edit-aircraft":
            return edit_aircraft_layout()
        else:
            return html.H1("404 - Page not found")

    @app.callback(
        Output("aircraft-data-store", "data"),
        Input("url", "pathname"),
        prevent_initial_call=True
    )
    def reload_aircraft_on_return(pathname):
        # We no longer reload from disk on navigation.
        # The store is initialized at layout time and updated by save/upload.
        raise PreventUpdate

    @app.callback(
        Output("aircraft-select", "value", allow_duplicate=True),
        Input("aircraft-data-store", "data"),
        State("last-saved-aircraft", "data"),
        prevent_initial_call=True
    )
    def set_last_selected_aircraft_on_load(data, last_saved):
        if last_saved and last_saved in data:
            return last_saved
        raise PreventUpdate

