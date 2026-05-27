"""TallyAero EM Diagram — environment input callbacks: altitude, OAT, altimeter, airport defaulting + live METAR fetch."""

from __future__ import annotations

import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate

from em_core import (
    LAPSE_RATE_K_FT, TEMP_SL_C,
    compute_density_altitude, compute_pressure_altitude,
    AIRPORT_DATA, AIRPORT_OPTIONS, get_airport_by_id,
    dprint,
)
from services.weather import get_metar


def _flight_category_color(cat: str | None) -> str:
    """Return the standard AWC flight-category color."""
    return {
        "VFR":  "#198754",  # green
        "MVFR": "#0d6efd",  # blue
        "IFR":  "#dc3545",  # red
        "LIFR": "#6f42c1",  # purple
    }.get((cat or "").upper(), "#6c757d")


def _format_age(seconds: int | None) -> str:
    """Human-readable observation age."""
    if seconds is None:
        return ""
    m = seconds // 60
    if m < 1:
        return "just now"
    if m < 60:
        return f"{m} min ago"
    h, m = divmod(m, 60)
    return f"{h}h {m}m ago" if m else f"{h}h ago"


def register(app):
    """Install every callback in this module."""

    # Phase 5AB-2b: airport options loaded lazily. Initial page payload was
    # serializing ~49k airport options = 5.1 MB of JSON shipped on every
    # load. We now keep options=[] in the layout and fill on search.
    @app.callback(
        Output("airport-select", "options"),
        Input("airport-select", "search_value"),
        State("airport-select", "value"),
    )
    def populate_airport_options(search_value, selected):
        """Return up to 50 matches for the typed query, plus the currently
        selected option (so react-select can still render its label)."""
        opts = []
        if selected:
            sel = next((o for o in AIRPORT_OPTIONS if o["value"] == selected), None)
            if sel:
                opts.append(sel)
        if not search_value:
            return opts
        needle = search_value.lower()
        matches = []
        for o in AIRPORT_OPTIONS:
            if o["value"] == selected:
                continue                    # already in opts
            if needle in o["label"].lower():
                matches.append(o)
                if len(matches) >= 50:
                    break
        return opts + matches

    @app.callback(
        Output("altitude-slider", "min"),
        Output("altitude-slider", "value"),
        Output("altitude-slider", "marks", allow_duplicate=True),
        Output("oat-input",      "value", allow_duplicate=True),
        Output("altimeter-input","value", allow_duplicate=True),
        Output("metar-store",    "data"),
        Input("airport-select", "value"),
        State("altitude-slider", "value"),
        State("altitude-slider", "max"),
        prevent_initial_call=True,
    )
    def update_environment_from_airport(airport_id, current_alt, max_alt):
        """Pick an airport → update altitude slider, attempt METAR fetch, and
        seed OAT + altimeter from the live observation when available. Falls
        back to ISA at field elevation + 29.92" when no METAR exists.

        Owns 6 outputs because the airport-pick is the single user gesture
        that drives the whole environment block. Keeping them in one callback
        avoids races between the slider, METAR, and ISA fallback.
        """
        if not airport_id:
            # Cleared — reset everything to sea-level / ISA / standard.
            marks = {i: f"{i // 1000}k" for i in range(0, int(max_alt) + 1, 5000) if i > 0}
            marks[0] = "SL"
            return 0, 0, marks, 15, 29.92, None

        airport = get_airport_by_id(AIRPORT_DATA, airport_id)
        if not airport:
            return 0, current_alt, dash.no_update, dash.no_update, dash.no_update, None

        # --- Altitude slider min/value/marks ---
        field_elev = airport.get("elevation_ft", 0) or 0
        field_elev_rounded = int(round(field_elev / 100) * 100)
        marks = {i: f"{i // 1000}k" for i in range(0, int(max_alt) + 1, 5000) if i > 0 and i >= field_elev_rounded}
        marks[field_elev_rounded] = "Field"
        if max_alt not in marks:
            marks[int(max_alt)] = f"{int(max_alt) // 1000}k"
        new_alt = max(field_elev_rounded, current_alt) if current_alt else field_elev_rounded

        # --- METAR fetch — best-effort, with ISA fallback ---
        # Try the ICAO field first (clean 4-letter for major airports). Falls
        # back to the bare id for the small fields where id IS the LID
        # (00AA-style) — NOAA AWC accepts these too for some airports.
        icao = airport.get("icao") or airport.get("id")
        metar = get_metar(icao) if icao else None

        if metar and metar.temp_c is not None and metar.altimeter_inhg is not None:
            return (
                field_elev_rounded, new_alt, marks,
                round(metar.temp_c),
                metar.altimeter_inhg,
                metar.to_dict(),
            )

        # Fall back to ISA at field elevation. Altimeter stays at standard.
        isa = TEMP_SL_C - field_elev_rounded * LAPSE_RATE_K_FT
        return field_elev_rounded, new_alt, marks, round(isa), 29.92, None

    @app.callback(
        Output("pa-da-display", "children"),
        Input("altitude-slider", "value"),
        Input("oat-input", "value"),
        Input("altimeter-input", "value"),
    )
    def update_pa_da_display(field_elev, oat_c, altimeter):
        """Calculate and display Pressure Altitude and Density Altitude."""
        field_elev = field_elev or 0
        oat_c = oat_c if oat_c is not None else 15
        altimeter = altimeter if altimeter is not None else 29.92

        # Calculate Pressure Altitude
        pa = compute_pressure_altitude(field_elev, altimeter)

        # Calculate Density Altitude
        da = compute_density_altitude(pa, oat_c)

        # Calculate ISA temperature at this altitude for reference
        isa_temp = TEMP_SL_C - (pa * LAPSE_RATE_K_FT)

        # Color code DA based on how much above PA it is
        da_diff = da - pa
        if da_diff > 3000:
            da_color = "#dc3545"  # Red - hot day, significant DA increase
        elif da_diff > 1000:
            da_color = "#fd7e14"  # Orange - warm
        elif da_diff < -1000:
            da_color = "#0d6efd"  # Blue - cold
        else:
            da_color = "#198754"  # Green - near standard

        return html.Div([
            html.Span(f"PA: {int(pa):,} ft", style={"marginRight": "15px", "fontSize": "12px"}),
            html.Span(f"DA: {int(da):,} ft", style={"color": da_color, "fontWeight": "bold", "fontSize": "12px"}),
            html.Span(f" (ISA: {isa_temp:.0f}°C)", style={"fontSize": "10px", "color": "#888", "marginLeft": "8px"})
        ])

    @app.callback(
        Output("oat-input", "value", allow_duplicate=True),
        Input("altitude-slider", "value"),
        State("airport-select", "value"),
        prevent_initial_call=True,
    )
    def update_default_oat_no_airport(field_elev, airport_id):
        """When no airport is selected, slide-altitude → ISA OAT (ad-hoc
        what-if exploration). When an airport IS selected, the METAR (or
        ISA-at-field-elev) seed from update_environment_from_airport wins,
        so we leave OAT alone."""
        if airport_id:
            raise PreventUpdate
        field_elev = field_elev or 0
        isa_temp = TEMP_SL_C - (field_elev * LAPSE_RATE_K_FT)
        return round(isa_temp)

    @app.callback(
        Output("weather-panel", "children"),
        Output("weather-panel", "className"),
        Input("metar-store", "data"),
        State("airport-select", "value"),
    )
    def render_weather_panel(metar_data, airport_id):
        """Render the live-weather panel under the airport picker."""
        if not airport_id:
            return None, "weather-panel weather-panel-empty"

        # No airport-side state, just a hint that ISA defaults are in use.
        if not metar_data:
            return html.Div([
                html.Div("No live observation — using ISA / 29.92\" defaults.",
                         className="weather-msg"),
            ]), "weather-panel weather-panel-fallback"

        m = metar_data
        cat = m.get("flight_category")
        cat_color = _flight_category_color(cat)
        wind_str = ""
        if m.get("wind_speed_kt") is not None:
            wdir = m.get("wind_dir_deg")
            wdir_s = f"{int(wdir):03d}°" if isinstance(wdir, (int, float)) else "VRB"
            wind_str = f"{wdir_s} @ {m['wind_speed_kt']}kt"
            if m.get("wind_gust_kt"):
                wind_str += f" G{m['wind_gust_kt']}"

        age_s = None
        if m.get("obs_time_epoch"):
            import time as _t
            age_s = max(0, int(_t.time() - m["obs_time_epoch"]))
        age_str = _format_age(age_s)

        return html.Div([
            html.Div([
                html.Span("Live obs", className="weather-tag"),
                html.Span(age_str, className="weather-age"),
                html.Span(cat or "", className="weather-cat",
                          style={"backgroundColor": cat_color}) if cat else None,
            ], className="weather-header"),
            html.Div([
                html.Span(f"{round(m['temp_c'])}°C", className="weather-temp")
                    if m.get("temp_c") is not None else None,
                html.Span(f" / dew {round(m['dewpoint_c'])}°C", className="weather-dew")
                    if m.get("dewpoint_c") is not None else None,
                html.Span(f" · {m['altimeter_inhg']}\"", className="weather-altim")
                    if m.get("altimeter_inhg") is not None else None,
            ], className="weather-line"),
            html.Div([
                html.Span(wind_str, className="weather-wind") if wind_str else None,
                html.Span(f" · {m['sky_cover']}", className="weather-sky") if m.get("sky_cover") else None,
                html.Span(f" · vis {m['visibility']}", className="weather-vis") if m.get("visibility") else None,
            ], className="weather-line"),
            html.Div(m.get("raw") or "", className="weather-raw")
                if m.get("raw") else None,
            html.Div("via NOAA Aviation Weather Center",
                     className="weather-attribution"),
        ]), "weather-panel weather-panel-active"

    @app.callback(
        Output("oat-fahrenheit-display", "children"),
        Input("oat-input", "value"),
    )
    def update_oat_fahrenheit(oat_c):
        """Convert OAT from Celsius to Fahrenheit for display.

        Phase 5AB-2b: target is now an html.Span (was a disabled dcc.Input),
        so we write `children` not `value`.
        """
        oat_c = oat_c if oat_c is not None else 15
        oat_f = (oat_c * 9/5) + 32
        return f"{oat_f:.0f}"

    # Phase 5AB-2: chip-label sync callbacks and the popover mutual-exclusion
    # callback removed. Atmosphere inputs are now inline in the rail, so there
    # are no chips to label and no env popovers to coordinate. Compare popover
    # is the only remaining popover and uses dbc.Popover's native click toggle.

