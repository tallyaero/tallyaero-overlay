"""Aircraft-config callbacks - maneuver dispatch, pylons input sync,
aircraft-field cascade, climb-speed autofill, runway dropdown population
for impossible-turn / power-off 180 / engine-out.

Every callback here owns inputs the pilot adjusts to configure the
aircraft (engine, occupants, fuel, CG) or to wire the airport/runway
selection into per-maneuver UI."""

from __future__ import annotations

from dash import Input, Output, State

from layouts.maneuvers.impossible_turn import impossible_turn_layout
from layouts.maneuvers.poweroff180 import poweroff180_layout
from layouts.maneuvers.engineout import engineout_layout
from layouts.maneuvers.steep_turn import steep_turn_layout
from layouts.maneuvers.chandelle import chandelle_layout
from layouts.maneuvers.lazy_eight import lazy8_layout
from layouts.maneuvers.steep_spiral import steep_spiral_layout
from layouts.maneuvers.s_turn import s_turn_layout
from layouts.maneuvers.turns_around_point import turns_point_layout
from layouts.maneuvers.rectangular_course import rect_course_layout
from layouts.maneuvers.eights_on_pylons import pylons_layout
from layouts.maneuvers.route import route_layout

from core.data_loader import aircraft_data, airport_data


def register(app):
    """Install every aircraft-config callback against the given Dash app."""

    @app.callback(
        Output("maneuver-params-container", "children"),
        Input("maneuver-select", "value"),
        Input("aircraft-select", "value"),
        State("selected-airport-id", "data")
    )
    def render_maneuver_layout(maneuver, aircraft_name, airport_id):
        elev_ft = None
        if airport_id:
            ap = next((a for a in airport_data if a["id"] == airport_id), None)
            elev_ft = ap.get("elevation_ft", None) if ap else None

        if maneuver == "route":
            gr = gi = tas = ci = vx = vy = None
            if aircraft_name and aircraft_name in aircraft_data:
                ac = aircraft_data[aircraft_name]
                sel = ac.get("single_engine_limits") or {}
                gr = sel.get("best_glide_ratio")
                gi = sel.get("best_glide")
                vx = ac.get("Vx")
                vy = ac.get("Vy")
                # Default planning TAS = 85% of Vno (top of green arc), a
                # standard ~75% power cruise approximation. Vno is present
                # on every aircraft via arcs.green[1] or top-level Vno.
                vno = ac.get("Vno")
                if not vno:
                    arcs = ac.get("arcs") or {}
                    green = arcs.get("green") or []
                    if len(green) >= 2:
                        vno = green[1]
                tas = round(vno * 0.85) if vno else None
                ci = vy   # default climb IAS = Vy
            is_me = (ac.get("engine_count") or 1) >= 2 if ac else False
            return route_layout(default_glide_ratio=gr,
                                default_glide_ias=gi,
                                default_tas=tas,
                                default_climb_ias=ci,
                                vx_kt=vx, vy_kt=vy,
                                is_multi_engine=is_me)
        if maneuver == "impossible_turn":
            return impossible_turn_layout()
        elif maneuver == "poweroff180":
            return poweroff180_layout(default_elev=elev_ft)
        elif maneuver == "engineout":
            return engineout_layout()
        elif maneuver == "steep_turn":
            return steep_turn_layout()
        elif maneuver == "chandelle":
            return chandelle_layout()
        elif maneuver == "lazy8":
            return lazy8_layout()
        elif maneuver == "steep_spiral":
            return steep_spiral_layout()
        elif maneuver == "s_turn":
            return s_turn_layout()
        elif maneuver == "turns_point":
            return turns_point_layout()
        elif maneuver == "rect_course":
            return rect_course_layout()
        elif maneuver == "pylons":
            return pylons_layout()
        return []

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
        """Populate runway dropdown when airport is selected or maneuver changes."""
        if not airport_id:
            return [], None, "Select airport first...", "", {"display": "block"}

        # Find airport in data
        airport = next((a for a in airport_data if a.get("id") == airport_id), None)
        if not airport:
            return [], None, "Airport not found", "", {"display": "block"}

        # Get runways
        runways = airport.get("runways", [])
        if not runways:
            return [], None, "No runway data available", "Use manual heading below", {"display": "block"}

        # Build options - format: "17 (170° - 5,500 ft)"
        options = []
        for rwy in runways:
            rwy_id = rwy.get("id", "?")
            heading = rwy.get("heading")
            length = rwy.get("length_ft", 0)

            if heading is not None:
                label = f"{rwy_id} ({heading:03d}° - {length:,} ft)"
            else:
                label = f"{rwy_id} ({length:,} ft)"

            options.append({"label": label, "value": rwy_id})

        # Sort by runway ID
        options.sort(key=lambda x: x["value"])

        # Default to first runway with valid heading
        default_value = None
        for opt in options:
            rwy = next((r for r in runways if r.get("id") == opt["value"]), None)
            if rwy and rwy.get("heading") is not None:
                default_value = opt["value"]
                break

        if not default_value and options:
            default_value = options[0]["value"]

        info_text = f"{airport.get('name', airport_id)} - {len(runways)} runway(s)"

        # Hide manual heading when runway dropdown has options
        manual_style = {"display": "none"} if options else {"display": "block"}

        return options, default_value, "Select runway...", info_text, manual_style

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
        """Populate runway dropdown for heading selection in Power-Off 180."""
        if not airport_id:
            return [], None, "Select airport for runway heading...", "Or use manual heading below", {"display": "block"}

        # Find airport in data
        airport = next((a for a in airport_data if a.get("id") == airport_id), None)
        if not airport:
            return [], None, "Airport not found", "Use manual heading below", {"display": "block"}

        # Get runways
        runways = airport.get("runways", [])
        if not runways:
            return [], None, "No runway data", "Use manual heading below", {"display": "block"}

        # Build options - format: "17 (170° - 5,500 ft)"
        options = []
        for rwy in runways:
            rwy_id = rwy.get("id", "?")
            heading = rwy.get("heading")
            length = rwy.get("length_ft", 0)

            if heading is not None:
                label = f"{rwy_id} ({heading:03d}° - {length:,} ft)"
            else:
                label = f"{rwy_id} ({length:,} ft)"

            options.append({"label": label, "value": rwy_id})

        # Sort by runway ID
        options.sort(key=lambda x: x["value"])

        # Default to first runway with valid heading
        default_value = None
        for opt in options:
            rwy = next((r for r in runways if r.get("id") == opt["value"]), None)
            if rwy and rwy.get("heading") is not None:
                default_value = opt["value"]
                break

        if not default_value and options:
            default_value = options[0]["value"]

        info_text = f"{airport.get('name', airport_id)} - select runway for heading"

        # Hide manual heading when runway dropdown has valid options
        manual_style = {"display": "none"} if options else {"display": "block"}

        return options, default_value, "Select runway...", info_text, manual_style

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
        """Populate runway dropdown for Engine-Out Glide Simulator."""
        if not airport_id:
            return [], None, "Select airport for runway...", "Or use manual heading below", {"display": "block"}

        # Find airport in data
        airport = next((a for a in airport_data if a.get("id") == airport_id), None)
        if not airport:
            return [], None, "Airport not found", "Use manual heading below", {"display": "block"}

        # Get runways
        runways = airport.get("runways", [])
        if not runways:
            return [], None, "No runway data", "Use manual heading below", {"display": "block"}

        # Build options - format: "17 (170° - 5,500 ft)"
        options = []
        for rwy in runways:
            rwy_id = rwy.get("id", "?")
            heading = rwy.get("heading")
            length = rwy.get("length_ft", 0)

            if heading is not None:
                label = f"{rwy_id} ({heading:03d}° - {length:,} ft)"
            else:
                label = f"{rwy_id} ({length:,} ft)"

            options.append({"label": label, "value": rwy_id})

        # Sort by runway ID
        options.sort(key=lambda x: x["value"])

        # Default to first runway with valid heading
        default_value = None
        for opt in options:
            rwy = next((r for r in runways if r.get("id") == opt["value"]), None)
            if rwy and rwy.get("heading") is not None:
                default_value = opt["value"]
                break

        if not default_value and options:
            default_value = options[0]["value"]

        info_text = f"{airport.get('name', airport_id)} - select runway for heading"

        # Hide manual heading when runway dropdown has valid options
        manual_style = {"display": "none"} if options else {"display": "block"}

        return options, default_value, "Select runway...", info_text, manual_style
