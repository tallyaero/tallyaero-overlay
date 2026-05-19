"""Environment input callbacks - airport search, selection, recenter,
weight display. Owns inputs the pilot adjusts to set environmental
context for a maneuver."""

from __future__ import annotations

from dash import html, Input, Output, State, ALL, ctx, no_update
from dash.exceptions import PreventUpdate

from core.data_loader import aircraft_data, airport_data
from core.log import get_logger

log = get_logger(__name__)


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
        Output("map", "viewport", allow_duplicate=True),
        Output("env-airport-agl", "children"),
        Output("selected-airport-id", "data"),
        Output("airport-search-input", "value"),
        Output("selected-airport-display", "children"),
        Output("selected-airport-display", "style"),
        Output("airport-search-results", "children", allow_duplicate=True),
        # Phase H — live weather auto-fill outputs.
        Output("env-wind-dir", "value", allow_duplicate=True),
        Output("env-wind-speed", "value", allow_duplicate=True),
        Output("env-oat", "value", allow_duplicate=True),
        Output("env-altimeter", "value", allow_duplicate=True),
        Output("wind-profile-store", "data", allow_duplicate=True),
        Output("active-metar-store", "data", allow_duplicate=True),
        # Phase H follow-up — green tint on fields filled from METAR.
        Output("env-wind-dir", "className", allow_duplicate=True),
        Output("env-wind-speed", "className", allow_duplicate=True),
        Output("env-oat", "className", allow_duplicate=True),
        Output("env-altimeter", "className", allow_duplicate=True),
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

        Phase H additions: best-effort fetch of (a) the surface METAR
        for the airport's ICAO (sets env-wind/OAT/altimeter, magvar-
        converted to TRUE for the sims) and (b) a 6-layer winds-aloft
        column at the airport's coords. Both are stored in dcc.Store
        so the altitude-changing sims can do per-tick wind lookup
        during a draw. Network failures fall back to no_update — the
        sidebar's current values stick.
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
        viewport = {"center": [lat, lon], "zoom": 14, "transition": "flyTo"}
        persisted_code = ap.get("icao") or ap.get("id") or airport_id

        # ---- Phase H · best-effort live weather fetch ----
        metar = None
        try:
            from core.metar import fetch_metar
            icao_for_metar = (ap.get("icao") or "").upper().strip()
            if icao_for_metar:
                metar = fetch_metar(icao_for_metar)
        except Exception as e:
            log.warning(f"METAR fetch failed for {airport_id}: {e}")

        wind_profile_data = no_update
        try:
            from core.winds_aloft import wind_column_at_point
            profile = wind_column_at_point(float(lat), float(lon),
                                            surface_metar=metar)
            if profile is not None:
                wind_profile_data = profile.to_store()
        except Exception as e:
            log.warning(f"Winds-aloft column fetch failed for {airport_id}: {e}")

        # Compute env-input fills (no_update preserves the user's
        # current sidebar value if METAR is missing or partial).
        wind_dir_fill = no_update
        wind_speed_fill = no_update
        oat_fill = no_update
        altim_fill = no_update
        metar_store = no_update
        # className outputs default to base; flip to '...field-live'
        # when METAR provides the value. Reset to base when METAR
        # didn't fill so a previous green tint clears on a new pick.
        BASE_CLS = "input-small"
        LIVE_CLS = "input-small field-live"
        wind_dir_cls = BASE_CLS
        wind_speed_cls = BASE_CLS
        oat_cls = BASE_CLS
        altim_cls = BASE_CLS
        if metar:
            md = metar.get("wind_dir_deg")
            ms = metar.get("wind_speed_kt")
            if md is not None:
                try:
                    from core.route import magvar_west_positive
                    magvar_w = float(magvar_west_positive(
                        float(lat), float(lon),
                        float(ap.get("elevation_ft", 0.0) or 0.0),
                    ))
                except Exception:
                    magvar_w = 0.0
                wind_dir_fill = int(round((float(md) - magvar_w) % 360.0))
                wind_dir_cls = LIVE_CLS
            if ms is not None:
                wind_speed_fill = int(round(float(ms)))
                wind_speed_cls = LIVE_CLS
            temp_c = metar.get("temp_c")
            if temp_c is not None:
                oat_fill = int(round(float(temp_c) * 9.0 / 5.0 + 32.0))
                oat_cls = LIVE_CLS
            altim = metar.get("altimeter_inhg")
            if altim is not None:
                altim_fill = round(float(altim), 2)
                altim_cls = LIVE_CLS
            metar_store = metar

        return (
            viewport, f"{elev} ft", airport_id, persisted_code,
            f"Selected: {name} ({airport_id})", display_style, [],
            wind_dir_fill, wind_speed_fill, oat_fill, altim_fill,
            wind_profile_data, metar_store,
            wind_dir_cls, wind_speed_cls, oat_cls, altim_cls,
        )

    @app.callback(
        Output("sidebar-live-weather", "children"),
        Input("active-metar-store", "data"),
        Input("wind-profile-store", "data"),
    )
    def render_live_weather_panel(metar, wind_profile_data):
        """Sidebar Live Weather panel — renders the parsed METAR + the
        winds-aloft column the sims will consume. Empty when no live
        data is staged (no airport picked, or both fetches failed).
        """
        if not metar and not wind_profile_data:
            return None

        children = [html.Div("Live Weather", className="lw-title")]

        if metar:
            icao = metar.get("icao") or ""
            obs_time = metar.get("obs_time") or ""
            wind_d = metar.get("wind_dir_deg")
            wind_s = metar.get("wind_speed_kt")
            wind_g = metar.get("wind_gust_kt")
            temp_c = metar.get("temp_c")
            altim = metar.get("altimeter_inhg")
            raw_ob = metar.get("raw_ob") or ""

            obs_short = ""
            if obs_time:
                # ISO "2026-05-19T13:55:00Z" → "13:55Z"
                try:
                    obs_short = obs_time[11:16] + "Z"
                except Exception:
                    obs_short = ""

            line1_parts = [
                html.Span(icao, className="lw-icao"),
                html.Span(f"  {obs_short}", className="lw-time"),
            ]
            wind_str = ""
            if wind_d is not None and wind_s is not None:
                wind_str = f"{int(wind_d):03d}°/{int(wind_s)}"
                if wind_g:
                    wind_str += f"G{int(wind_g)}"
            elif wind_s is not None:
                wind_str = f"VRB/{int(wind_s)}"

            stat_bits = []
            if wind_str:
                stat_bits.append(f"Wind {wind_str} kt")
            if temp_c is not None:
                stat_bits.append(f"OAT {int(round(temp_c))}°C")
            if altim is not None:
                stat_bits.append(f"Altim {altim:.2f}″")

            children.append(html.Div(line1_parts))
            if stat_bits:
                children.append(html.Div(" · ".join(stat_bits)))
            if raw_ob:
                children.append(html.Div(raw_ob, className="lw-raw"))

        # Winds-aloft layers — show up to ~4 useful layers (skip empty).
        layers = (wind_profile_data or {}).get("layers") or []
        if layers:
            children.append(html.Hr(style={
                "margin": "6px 0",
                "borderTop": "1px dashed var(--ta-border-primary, #e2e8f0)",
            }))
            children.append(html.Div("Winds aloft (true)",
                                      className="lw-title"))
            for alt_ft, dir_deg, kt in layers:
                if alt_ft <= 0:
                    label = "SFC"
                elif alt_ft < 10000:
                    label = f"{int(alt_ft):,} ft"
                else:
                    label = f"{int(alt_ft / 1000)}k"
                value = (f"{int(round(dir_deg)) % 360:03d}°/"
                         f"{int(round(kt))} kt")
                children.append(html.Div(
                    [
                        html.Span(label, className="lw-aloft-alt"),
                        html.Span(value),
                    ],
                    className="lw-aloft-row",
                ))

        return html.Div(children, className="live-weather-panel")

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
