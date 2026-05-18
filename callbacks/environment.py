"""Environment input callbacks - airport search, selection, recenter,
weight display. Owns inputs the pilot adjusts to set environmental
context for a maneuver."""

from __future__ import annotations

from dash import html, Input, Output, State, ALL, ctx
from dash.exceptions import PreventUpdate

from core.data_loader import aircraft_data, airport_data


_AP_SEARCH_FIELDS = ("id", "name", "icao", "iata", "local", "municipality", "state")


def _airport_matches(ap: dict, q: str) -> bool:
    """Case-insensitive substring match across ID, name, ICAO, IATA, FAA LID,
    municipality, and US state. Empty/None fields skipped automatically."""
    for f in _AP_SEARCH_FIELDS:
        v = ap.get(f)
        if v and q in v.lower():
            return True
    return False


def _airport_label(ap: dict) -> str:
    """Format a search-result label: short-code · name — locality.

    short-code prefers IATA, then ICAO, then ID. Locality prefers
    "city, state" (US) → "city, country" → country → empty.
    """
    short = ap.get("iata") or ap.get("icao") or ap.get("id", "")
    name = ap.get("name", "")
    city = ap.get("municipality") or ""
    state = ap.get("state") or ""
    country = ap.get("country") or ""
    if city and state:
        locality = f"{city}, {state}"
    elif city and country:
        locality = f"{city}, {country}"
    elif country:
        locality = country
    else:
        locality = ""
    prefix = f"{short} · {name}" if short and short != ap.get("id") else f"{name} ({ap.get('id','')})"
    return f"{prefix} — {locality}" if locality else prefix


def register(app):
    """Install every environment callback against the given Dash app."""

    @app.callback(
        Output("total-weight-display", "value"),
        Output("runtime-total-weight-lb", "data"),
        Input("aircraft-select", "value"),
        Input("occupants", "value"),
        Input("occupant-weight", "value"),
        Input("fuel-load", "value"),
    )
    def update_total_weight_display(ac_name, occupants, occupant_wt, fuel_gal):
        if not ac_name or ac_name not in aircraft_data:
            return "", None

        ac = aircraft_data[ac_name]
        empty_wt = float(ac.get("empty_weight", 0.0))
        fuel_per_gal = float(ac.get("fuel_weight_per_gal", 6.0))

        occ = float(occupants or 0)
        occ_wt = float(occupant_wt or 0)
        fuel = float(fuel_gal or 0)

        total = empty_wt + (occ * occ_wt) + (fuel * fuel_per_gal)
        total_round = int(round(total))

        return f"{total_round}", total

    @app.callback(
        Output("map", "viewport"),
        Output("env-airport-agl", "children"),
        Output("selected-airport-id", "data"),
        Output("airport-search-input", "value"),
        Output("selected-airport-display", "children"),
        Output("selected-airport-display", "style"),
        Output("airport-search-results", "children", allow_duplicate=True),
        Input({"type": "airport-result", "index": ALL}, "n_clicks"),
        Input("airport-search-input", "n_submit"),
        State("airport-search-matches", "data"),
        prevent_initial_call=True,
    )
    def handle_airport_pick(n_clicks_list, n_submit, current_matches):
        """Two paths to the same outcome:
          - User clicks a result row in the dropdown (existing).
          - User presses Enter in the search input → picks the top
            match from airport-search-matches (autocomplete behavior).
        After selection, map auto-zooms to an airport-area view
        (zoom 14, ~2 NM radius around the airport) so runway+pattern
        geometry is visible without manual pan/zoom.
        """
        trigger = ctx.triggered_id
        airport_id = None

        # Enter-key path
        if trigger == "airport-search-input":
            if not current_matches:
                raise PreventUpdate
            airport_id = current_matches[0]
        elif isinstance(trigger, dict):
            # Result-row click path
            if (not n_clicks_list
                    or all(n is None or n == 0 for n in n_clicks_list)):
                raise PreventUpdate
            airport_id = trigger.get("index")

        if not airport_id:
            raise PreventUpdate
        ap = next((a for a in airport_data if a.get("id") == airport_id), None)
        if not ap:
            raise PreventUpdate

        lat, lon = ap["lat"], ap["lon"]
        elev = ap.get("elevation_ft", "---")
        name = ap.get("name", airport_id)

        display_style = {
            "fontSize": "12px",
            "color": "#28a745",
            "fontWeight": "500",
            "marginTop": "4px",
            "marginBottom": "4px",
            "display": "block",
        }
        # Airport-area zoom — zoom 14 gives ~2 NM radius around the
        # airport so runway + traffic pattern geometry is visible.
        # dash-leaflet 1.0.15: `center`/`zoom` are initial-only props;
        # programmatic re-centering requires the `viewport` dict.
        viewport = {"center": [lat, lon], "zoom": 14, "transition": "flyTo"}
        return (viewport, f"{elev} ft", airport_id, "",
                f"Selected: {name} ({airport_id})", display_style, [])

    @app.callback(
        Output("airport-search-results", "children"),
        Output("airport-search-matches", "data"),
        Output("airport-highlight-index", "data"),
        Input("airport-search-input", "value"),
    )
    def search_airport_database(query):
        """Search airports as user types. Results appear below input.

        Delegates to core.airport_search so the top-bar search behaves
        identically to the Route waypoint dropdown — same ranked
        scoring (exact code > prefix > city > name > state), same
        result label format. Previously this had its own substring
        matcher with no ranking, which led to inconsistent results
        between the two surfaces.
        """
        from core.airport_search import (
            search_airports as _search_airports,
            airport_label as _airport_label_v2,
        )
        if not query or len(query.strip()) < 2:
            return [], [], 0
        hits = _search_airports(airport_data, query, limit=10)
        match_ids = [ap["id"] for ap in hits]
        results = [
            html.Div(
                _airport_label_v2(ap),
                className="airport-result",
                id={"type": "airport-result", "index": ap["id"]},
                n_clicks=0,
            )
            for ap in hits
        ]
        return results, match_ids, 0

    @app.callback(
        Output("selected-airport-display", "children", allow_duplicate=True),
        Output("selected-airport-display", "style", allow_duplicate=True),
        Output("env-airport-agl", "children", allow_duplicate=True),
        Input("selected-airport-id", "data"),
        prevent_initial_call=False  # Run on page load
    )
    def restore_airport_display_on_load(airport_id):
        """Restore the airport display when page loads with persisted airport."""
        hidden_style = {
            "fontSize": "12px",
            "color": "#28a745",
            "fontWeight": "500",
            "marginTop": "4px",
            "marginBottom": "4px",
            "display": "none"
        }

        if not airport_id:
            return "", hidden_style, "--- ft"

        ap = next((a for a in airport_data if a.get("id") == airport_id), None)
        if not ap:
            return "", hidden_style, "--- ft"

        name = ap.get("name", airport_id)
        elev = ap.get("elevation_ft", "---")

        display_style = {
            "fontSize": "12px",
            "color": "#28a745",
            "fontWeight": "500",
            "marginTop": "4px",
            "marginBottom": "4px",
            "display": "block"
        }

        # Only update the display - don't touch the search input
        return f"Selected: {name} ({airport_id})", display_style, f"{elev} ft"

    @app.callback(
        Output("map", "viewport", allow_duplicate=True),
        Input("recenter-airport-btn", "n_clicks"),
        State("selected-airport-id", "data"),
        prevent_initial_call=True
    )
    def recenter_to_airport(n_clicks, selected_id):
        """Recenter map to the selected airport at airport-area zoom."""
        if not n_clicks or not selected_id:
            raise PreventUpdate

        ap = next((a for a in airport_data if a.get("id") == selected_id), None)
        if not ap:
            raise PreventUpdate

        return {"center": [ap["lat"], ap["lon"]], "zoom": 14, "transition": "flyTo"}
