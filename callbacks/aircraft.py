"""Aircraft-config callbacks - maneuver dispatch, pylons input sync,
aircraft-field cascade, climb-speed autofill, runway dropdown population
for impossible-turn / power-off 180 / engine-out.

Every callback here owns inputs the pilot adjusts to configure the
aircraft (engine, occupants, fuel, CG) or to wire the airport/runway
selection into per-maneuver UI."""

from __future__ import annotations

from dash import Input, Output, State
from dash.exceptions import PreventUpdate

from layouts.maneuvers.impossible_turn import impossible_turn_layout, impossible_turn_actions
from layouts.maneuvers.poweroff180 import poweroff180_layout, poweroff180_actions
from layouts.maneuvers.engineout import engineout_layout, engineout_actions
from layouts.maneuvers.steep_turn import steep_turn_layout, steep_turn_actions
from layouts.maneuvers.chandelle import chandelle_layout, chandelle_actions
from layouts.maneuvers.lazy_eight import lazy8_layout, lazy8_actions
from layouts.maneuvers.steep_spiral import steep_spiral_layout, steep_spiral_actions
from layouts.maneuvers.s_turn import s_turn_layout, s_turn_actions
from layouts.maneuvers.turns_around_point import turns_point_layout, turns_point_actions
from layouts.maneuvers.rectangular_course import rect_course_layout, rect_course_actions
from layouts.maneuvers.eights_on_pylons import pylons_layout, pylons_actions
from layouts.maneuvers.route import route_layout

from core.data_loader import aircraft_data, airport_data


# ---------- Phase F · Runway-end auto-fill helpers ----------

def _airport_magvar(airport):
    """Magnetic variation at the airport (W-positive). Returns 0.0 if
    the airport has no lat/lon or the WMM lookup raises."""
    if not airport:
        return 0.0
    try:
        from core.route import magvar_west_positive
        return float(magvar_west_positive(
            float(airport.get("lat", 0.0)),
            float(airport.get("lon", 0.0)),
            float(airport.get("elevation_ft", 0.0)),
        ))
    except Exception:
        return 0.0


def _true_to_mag(true_deg, magvar_w):
    return int(round((float(true_deg) + float(magvar_w)) % 360.0))


def _mag_to_true(mag_deg, magvar_w):
    return float((float(mag_deg) - float(magvar_w)) % 360.0)


def _runway_end_options(airport):
    """Build (options, default_value) for a runway-select dropdown.

    Lists each runway END (e.g. "06" and "24" as separate rows), not
    the pair "06/24". The end id is the dropdown value so downstream
    callbacks can resolve lat/lon/heading from the picked end directly.

    Labels carry the magnetic heading (the number pilots read on their
    compass and on the runway designator). The raw `heading` stored on
    each end is TRUE — we convert to magnetic via the WMM at the
    airport's lat/lon. Falls back to pair-level entries for airports
    whose runway records don't carry an `ends` list.
    """
    runways = (airport or {}).get("runways", []) or []
    magvar_w = _airport_magvar(airport)
    options = []
    for rwy in runways:
        length = rwy.get("length_ft", 0) or 0
        ends = rwy.get("ends") or []
        if ends:
            for end in ends:
                eid = end.get("id", "?")
                hdg = end.get("heading")
                if hdg is not None:
                    mag = _true_to_mag(hdg, magvar_w)
                    label = f"{eid} ({mag:03d}° mag — {length:,} ft)"
                else:
                    label = f"{eid} ({length:,} ft)"
                options.append({"label": label, "value": eid})
        else:
            rid = rwy.get("id", "?")
            hdg = rwy.get("heading")
            if hdg is not None:
                mag = _true_to_mag(hdg, magvar_w)
                label = f"{rid} ({mag:03d}° mag — {length:,} ft)"
            else:
                label = f"{rid} ({length:,} ft)"
            options.append({"label": label, "value": rid})

    def _sort_key(opt):
        v = str(opt["value"])
        digits = "".join(c for c in v if c.isdigit())
        return (int(digits) if digits else 99, v)

    options.sort(key=_sort_key)
    default_value = options[0]["value"] if options else None
    return options, default_value


def _resolve_runway_end(airport_id, end_id):
    """Return the runway-end dict for the given airport + end id.

    Walks airport["runways"][*]["ends"] looking for a matching end.
    Falls back to matching pair-level id for legacy airports without
    `ends` records. The `heading` field on the returned dict is TRUE
    (matching what the data stores). Callers that need magnetic should
    convert via `_true_to_mag` with `_airport_magvar(airport)`.
    Returns None when nothing matches.
    """
    if not airport_id or not end_id:
        return None
    airport = next((a for a in airport_data if a.get("id") == airport_id), None)
    if not airport:
        return None
    for rwy in airport.get("runways", []) or []:
        for end in rwy.get("ends") or []:
            if str(end.get("id")) == str(end_id):
                merged = dict(end)
                merged.setdefault("length_ft", rwy.get("length_ft", 0))
                return merged
        if str(rwy.get("id")) == str(end_id):
            return rwy
    return None


def _resolve_runway_end_magnetic(airport_id, end_id):
    """Same as _resolve_runway_end but with `heading` converted to magnetic.

    Used by the auto-fill callbacks that write the heading number into a
    visible input field — pilots think in magnetic, the data stores true.
    """
    end = _resolve_runway_end(airport_id, end_id)
    if not end or end.get("heading") is None:
        return end
    airport = next((a for a in airport_data if a.get("id") == airport_id), None)
    magvar_w = _airport_magvar(airport)
    merged = dict(end)
    merged["heading_true"] = float(end["heading"])
    merged["heading"] = _true_to_mag(end["heading"], magvar_w)
    return merged


def register(app):
    """Install every aircraft-config callback against the given Dash app."""

    # Maneuvers ship their action buttons (Set X / Draw / Results)
    # in a separate `*_actions()` function alongside their layout, so
    # those buttons can be rendered into the floating overlay panel
    # next to Reset/Undo while the form fields stay in the top shelf.
    _ACTIONS_BY_MANEUVER = {
        "impossible_turn": impossible_turn_actions,
        "poweroff180": poweroff180_actions,
        "engineout": engineout_actions,
        "steep_turn": steep_turn_actions,
        "chandelle": chandelle_actions,
        "lazy8": lazy8_actions,
        "steep_spiral": steep_spiral_actions,
        "s_turn": s_turn_actions,
        "turns_point": turns_point_actions,
        "rect_course": rect_course_actions,
        "pylons": pylons_actions,
    }

    @app.callback(
        Output("maneuver-params-container", "children"),
        Output("maneuver-actions-container", "children"),
        Input("maneuver-select", "value"),
        Input("aircraft-select", "value"),
        State("selected-airport-id", "data")
    )
    def render_maneuver_layout(maneuver, aircraft_name, airport_id):
        elev_ft = None
        if airport_id:
            ap = next((a for a in airport_data if a["id"] == airport_id), None)
            elev_ft = ap.get("elevation_ft", None) if ap else None

        # Build the form fields (shelf) — same as before. Then look
        # up the per-maneuver actions builder; route mode + the
        # default fallthrough have no actions, so the overlay slot
        # stays empty.
        fields: list = []
        actions: list = []
        if maneuver == "route":
            gr = gi = tas = ci = vx = vy = None
            if aircraft_name and aircraft_name in aircraft_data:
                ac = aircraft_data[aircraft_name]
                sel = ac.get("single_engine_limits") or {}
                gr = sel.get("best_glide_ratio")
                gi = sel.get("best_glide")
                vx = ac.get("Vx")
                vy = ac.get("Vy")
                vno = ac.get("Vno")
                if not vno:
                    arcs = ac.get("arcs") or {}
                    green = arcs.get("green") or []
                    if len(green) >= 2:
                        vno = green[1]
                tas = round(vno * 0.85) if vno else None
                ci = vy
            is_me = (ac.get("engine_count") or 1) >= 2 if ac else False
            fields = route_layout(default_glide_ratio=gr,
                                  default_glide_ias=gi,
                                  default_tas=tas,
                                  default_climb_ias=ci,
                                  vx_kt=vx, vy_kt=vy,
                                  is_multi_engine=is_me)
        elif maneuver == "impossible_turn":
            fields = impossible_turn_layout()
        elif maneuver == "poweroff180":
            fields = poweroff180_layout(default_elev=elev_ft)
        elif maneuver == "engineout":
            fields = engineout_layout()
        elif maneuver == "steep_turn":
            fields = steep_turn_layout()
        elif maneuver == "chandelle":
            fields = chandelle_layout()
        elif maneuver == "lazy8":
            fields = lazy8_layout()
        elif maneuver == "steep_spiral":
            fields = steep_spiral_layout()
        elif maneuver == "s_turn":
            fields = s_turn_layout()
        elif maneuver == "turns_point":
            fields = turns_point_layout()
        elif maneuver == "rect_course":
            fields = rect_course_layout()
        elif maneuver == "pylons":
            fields = pylons_layout()

        actions_builder = _ACTIONS_BY_MANEUVER.get(maneuver)
        if actions_builder is not None:
            actions = actions_builder()

        return fields, actions

    @app.callback(
        Output("pylons-ias-store", "data"),
        Output("pylons-bank-store", "data"),
        Input("pylons-ias", "value"),
        Input("pylons-bank-angle", "value"),
        prevent_initial_call=True
    )
    def sync_pylons_inputs_to_stores(ias, bank):
        """Sync pylons input values to stores for click handler callback."""
        return (
            ias if ias is not None else 100,
            bank if bank is not None else 30
        )

    @app.callback(
        Output("engine-select", "options"),
        Output("engine-select", "value"),
        Output("occupants", "value"),
        Output("occupant-weight", "value"),
        Output("fuel-load", "max"),
        Output("fuel-load", "value"),
        Output("fuel-load", "marks"),
        Output("cg-slider", "min"),
        Output("cg-slider", "max"),
        Output("cg-slider", "value"),
        Output("cg-slider", "marks"),
        Input("aircraft-select", "value"),
        Input("maneuver-select", "value"),  # Also trigger when maneuver changes
        State("engine-select", "value"),
    )
    def update_aircraft_fields(selected_aircraft, maneuver, current_engine):
        if not selected_aircraft or selected_aircraft not in aircraft_data:
            return (
                [], None, 1, 180,
                50, 50,
                {0: "0", 12: "¼", 25: "½", 37: "¾", 50: "Full"},
                0.0, 1.0, 0.5,
                {0.0: "FWD", 0.5: "MID", 1.0: "AFT"}
            )

        ac = aircraft_data[selected_aircraft]

        engine_options = [{"label": k, "value": k} for k in ac.get("engine_options", {}).keys()]
        engine_values = [opt["value"] for opt in engine_options]
        # Preserve current engine if it's valid for this aircraft, otherwise use default
        if current_engine and current_engine in engine_values:
            selected_engine = current_engine
        else:
            selected_engine = engine_options[0]["value"] if engine_options else None
        seats = ac.get("seats", 2)
        default_occupants = min(seats, 2)
        default_weight = 180
        fuel_cap = ac.get("fuel_capacity_gal", 50)
        fuel_marks = {
            0: "0",
            int(0.25 * fuel_cap): "¼",
            int(0.5 * fuel_cap): "½",
            int(0.75 * fuel_cap): "¾",
            int(fuel_cap): "Full"
        }
        cg_range = ac.get("cg_range", [0.0, 1.0])
        cg_min = cg_range[0]
        cg_max = cg_range[1]
        cg_default = round((cg_min + cg_max) / 2, 2)
        cg_marks = {
            round(cg_min, 2): "FWD",
            round((cg_min + cg_max) / 2, 2): "MID",
            round(cg_max, 2): "AFT"
        }
        return (engine_options, selected_engine, default_occupants, default_weight, fuel_cap,
                fuel_cap, fuel_marks, cg_min, cg_max, cg_default, cg_marks)

    @app.callback(
        Output("impossibleturn-climb-speed", "value"),
        Input("aircraft-select", "value"),
        prevent_initial_call=True
    )
    def update_climb_speed_from_vy(selected_aircraft):
        """Auto-fill the Impossible Turn climb speed from aircraft Vy."""
        if not selected_aircraft or selected_aircraft not in aircraft_data:
            return 75  # Default fallback
        ac = aircraft_data[selected_aircraft]
        vy = ac.get("Vy")
        if vy is not None:
            return int(vy)
        return 75  # Default if no Vy data

    @app.callback(
        Output("impossibleturn-runway-select", "options"),
        Output("impossibleturn-runway-select", "value"),
        Output("impossibleturn-runway-select", "placeholder"),
        Output("impossibleturn-runway-info", "children"),
        Output("impossibleturn-manual-heading-div", "style"),
        Input("selected-airport-id", "data"),
        Input("maneuver-select", "value"),  # Also trigger when maneuver changes
        prevent_initial_call=False
    )
    def update_runway_options(airport_id, maneuver):
        """Populate the runway-end dropdown when an airport is selected."""
        if not airport_id:
            return [], None, "Select airport first...", "", {"display": "block"}

        airport = next((a for a in airport_data if a.get("id") == airport_id), None)
        if not airport:
            return [], None, "Airport not found", "", {"display": "block"}

        options, default_value = _runway_end_options(airport)
        if not options:
            return [], None, "No runway data available", "Use manual heading below", {"display": "block"}

        info_text = f"{airport.get('name', airport_id)} - {len(options)} runway end(s)"
        # Manual-heading override stays hidden as long as we have ends.
        manual_style = {"display": "none"}
        return options, default_value, "Departure runway...", info_text, manual_style

    @app.callback(
        Output("poweroff180-runway-select", "options"),
        Output("poweroff180-runway-select", "value"),
        Output("poweroff180-runway-select", "placeholder"),
        Output("poweroff180-runway-info", "children"),
        Output("poweroff180-manual-heading-div", "style"),
        Input("selected-airport-id", "data"),
        Input("maneuver-select", "value"),
        prevent_initial_call=False
    )
    def update_poweroff180_runway_options(airport_id, maneuver):
        """Populate the runway-end dropdown for Power-Off 180."""
        if not airport_id:
            return [], None, "Select airport for runway...", "Or use manual heading below", {"display": "block"}

        airport = next((a for a in airport_data if a.get("id") == airport_id), None)
        if not airport:
            return [], None, "Airport not found", "Use manual heading below", {"display": "block"}

        options, default_value = _runway_end_options(airport)
        if not options:
            return [], None, "No runway data", "Use manual heading below", {"display": "block"}

        info_text = f"{airport.get('name', airport_id)} - landing runway end"
        manual_style = {"display": "none"}
        return options, default_value, "Landing runway...", info_text, manual_style

    # ---------- Phase F2 · Heading auto-fill from runway end ----------

    @app.callback(
        Output("impossibleturn-manual-heading", "value", allow_duplicate=True),
        Input("impossibleturn-runway-select", "value"),
        State("selected-airport-id", "data"),
        prevent_initial_call=True,
    )
    def fill_impossibleturn_heading(end_id, airport_id):
        end = _resolve_runway_end_magnetic(airport_id, end_id)
        if not end or end.get("heading") is None:
            raise PreventUpdate
        return int(end["heading"])

    @app.callback(
        Output("poweroff180-manual-heading", "value", allow_duplicate=True),
        Input("poweroff180-runway-select", "value"),
        State("selected-airport-id", "data"),
        prevent_initial_call=True,
    )
    def fill_poweroff180_heading(end_id, airport_id):
        end = _resolve_runway_end_magnetic(airport_id, end_id)
        if not end or end.get("heading") is None:
            raise PreventUpdate
        return int(end["heading"])

    @app.callback(
        Output("engineout-touchdown-heading", "value", allow_duplicate=True),
        Input("engineout-runway-select", "value"),
        State("selected-airport-id", "data"),
        prevent_initial_call=True,
    )
    def fill_engineout_touchdown_heading(end_id, airport_id):
        end = _resolve_runway_end_magnetic(airport_id, end_id)
        if not end or end.get("heading") is None:
            raise PreventUpdate
        return int(end["heading"])

    # ---------- Phase F3 · Point-store auto-set from runway end ----------
    # When the user picks a runway end, place the relevant takeoff /
    # touchdown point at that end's threshold lat/lon. Eliminates the
    # need to manually click the runway on the map. The user can still
    # override by clicking the map after picking the runway (the click
    # handler writes to the same store).

    @app.callback(
        Output(
            {"type": "point-store", "m_id": "impossible_turn", "role": "start"},
            "data",
            allow_duplicate=True,
        ),
        Input("impossibleturn-runway-select", "value"),
        State("selected-airport-id", "data"),
        prevent_initial_call=True,
    )
    def fill_impossibleturn_start(end_id, airport_id):
        end = _resolve_runway_end(airport_id, end_id)
        if not end or end.get("lat") is None or end.get("lon") is None:
            raise PreventUpdate
        return {"lat": float(end["lat"]), "lon": float(end["lon"])}

    @app.callback(
        Output(
            {"type": "point-store", "m_id": "poweroff180", "role": "touchdown"},
            "data",
            allow_duplicate=True,
        ),
        Input("poweroff180-runway-select", "value"),
        State("selected-airport-id", "data"),
        prevent_initial_call=True,
    )
    def fill_poweroff180_touchdown(end_id, airport_id):
        end = _resolve_runway_end(airport_id, end_id)
        if not end or end.get("lat") is None or end.get("lon") is None:
            raise PreventUpdate
        return {"lat": float(end["lat"]), "lon": float(end["lon"])}

    @app.callback(
        Output(
            {"type": "point-store", "m_id": "engineout", "role": "touchdown"},
            "data",
            allow_duplicate=True,
        ),
        Input("engineout-runway-select", "value"),
        State("selected-airport-id", "data"),
        prevent_initial_call=True,
    )
    def fill_engineout_touchdown(end_id, airport_id):
        end = _resolve_runway_end(airport_id, end_id)
        if not end or end.get("lat") is None or end.get("lon") is None:
            raise PreventUpdate
        return {"lat": float(end["lat"]), "lon": float(end["lon"])}

    # ---------- Phase F · Hide Set Takeoff / Touchdown when runway picked ----------
    # Runway auto-fill already stages the threshold point; the Set button
    # becomes redundant. The user can still re-show it by clearing the
    # runway dropdown (clearable=True) to fall back to manual map-click.

    _HIDDEN = {"display": "none"}
    _SHOWN = {}  # let the default .shelf-action styles apply

    @app.callback(
        Output(
            {"type": "click-button", "m_id": "impossible_turn", "role": "start"},
            "style",
        ),
        Input("impossibleturn-runway-select", "value"),
    )
    def toggle_impossibleturn_set_btn(end_id):
        return _HIDDEN if end_id else _SHOWN

    @app.callback(
        Output(
            {"type": "click-button", "m_id": "poweroff180", "role": "touchdown"},
            "style",
        ),
        Input("poweroff180-runway-select", "value"),
    )
    def toggle_poweroff180_set_btn(end_id):
        return _HIDDEN if end_id else _SHOWN

    @app.callback(
        Output(
            {"type": "click-button", "m_id": "engineout", "role": "touchdown"},
            "style",
        ),
        Input("engineout-runway-select", "value"),
    )
    def toggle_engineout_set_td_btn(end_id):
        # Engine-Out's Set Start button stays — engine-failure point is
        # not on a runway. Only Set Touchdown hides.
        return _HIDDEN if end_id else _SHOWN

    @app.callback(
        Output("engineout-runway-select", "options"),
        Output("engineout-runway-select", "value"),
        Output("engineout-runway-select", "placeholder"),
        Output("engineout-runway-info", "children"),
        Output("engineout-manual-heading-div", "style"),
        Input("selected-airport-id", "data"),
        Input("maneuver-select", "value"),
        prevent_initial_call=False
    )
    def update_engineout_runway_options(airport_id, maneuver):
        """Populate the runway-end dropdown for Engine-Out Glide."""
        if not airport_id:
            return [], None, "Select airport for runway...", "Or use manual heading below", {"display": "block"}

        airport = next((a for a in airport_data if a.get("id") == airport_id), None)
        if not airport:
            return [], None, "Airport not found", "Use manual heading below", {"display": "block"}

        options, default_value = _runway_end_options(airport)
        if not options:
            return [], None, "No runway data", "Use manual heading below", {"display": "block"}

        info_text = f"{airport.get('name', airport_id)} - landing runway end"
        manual_style = {"display": "none"}
        return options, default_value, "Landing runway...", info_text, manual_style
