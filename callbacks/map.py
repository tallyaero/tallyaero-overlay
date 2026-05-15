"""Map-interaction callbacks - click target selection, scoped-store
writes, point summaries, undo, engineout touchdown elev autofill, click
location display - plus the map-coordinate helper functions
(get_elevation, calculate_runway_geometry, create_airplane_marker).

Every callback here touches the Leaflet map directly or maintains the
state that drives it. The three helpers live at module scope because
multiple callsites outside this module (the draw_* callbacks still in
app.py) consume them.
"""

from __future__ import annotations

import math

import requests

import dash
from dash import html, Input, Output, State, ALL, MATCH, ctx
from dash.exceptions import PreventUpdate
import dash_leaflet as dl

from core.log import get_logger

log = get_logger(__name__)


# ============================================================
# Module-level helpers - imported by draw_* callbacks too
# ============================================================
def get_elevation(lat, lon):
    if lat is None or lon is None:
        return None

    try:
        url = "https://api.open-meteo.com/v1/elevation"
        r = requests.get(url, params={"latitude": lat, "longitude": lon}, timeout=5)
        r.raise_for_status()
        data = r.json()

        elev_m = data.get("elevation")
        if isinstance(elev_m, list) and elev_m:
            elev_m = elev_m[0]

        if elev_m is None:
            return None

        return int(round(float(elev_m) * 3.28084))
    except Exception as e:
        log.error(f"Open-Meteo elevation lookup failed: {e}")
        return None


def calculate_runway_geometry(threshold_lat, threshold_lon, heading_deg, length_ft, width_ft=100):
    """
    Calculate runway polygon coordinates for map overlay.

    Args:
        threshold_lat: Latitude of runway threshold (clicked point)
        threshold_lon: Longitude of runway threshold
        heading_deg: Runway heading in degrees
        length_ft: Runway length in feet
        width_ft: Runway width in feet (default 100 ft)

    Returns:
        List of [lat, lon] coordinates for polygon corners
    """
    from physics import point_from, FT_PER_NM
    from geopy import Point as GeoPoint

    # Convert feet to nautical miles
    length_nm = length_ft / FT_PER_NM
    width_nm = width_ft / FT_PER_NM

    # Create threshold point object
    threshold = GeoPoint(threshold_lat, threshold_lon)

    # Calculate opposite threshold
    opposite = point_from(threshold, heading_deg, length_nm)

    # Calculate perpendicular heading for width
    perp_left = (heading_deg - 90) % 360
    perp_right = (heading_deg + 90) % 360
    half_width_nm = width_nm / 2

    # Corner 1: threshold left
    c1 = point_from(threshold, perp_left, half_width_nm)
    # Corner 2: threshold right
    c2 = point_from(threshold, perp_right, half_width_nm)
    # Corner 3: opposite right
    c3 = point_from(opposite, perp_right, half_width_nm)
    # Corner 4: opposite left
    c4 = point_from(opposite, perp_left, half_width_nm)

    return [
        [c1.latitude, c1.longitude],
        [c2.latitude, c2.longitude],
        [c3.latitude, c3.longitude],
        [c4.latitude, c4.longitude],
        [c1.latitude, c1.longitude],  # Close the polygon
    ]


def create_airplane_marker(pos, heading, tooltip_content, bank_angle=0, crab_angle=0, crab_exaggeration=3.0):
    """
    Create an airplane marker that points in the direction of flight.
    Uses an F-18 Super Hornet style fighter jet icon.

    Args:
        pos: [lat, lon] position
        heading: Aircraft heading in degrees (0=North, 90=East, etc.)
        tooltip_content: List of html elements for the tooltip
        bank_angle: Bank angle for visual tilt effect (optional)
        crab_angle: Actual crab angle in degrees (positive = crab right, negative = crab left)
        crab_exaggeration: Multiplier to exaggerate crab angle visually (default 3x)

    Returns:
        dl.Marker with rotated airplane icon
    """
    import base64
    import math

    # Exaggerate crab angle for visual effect only
    # The actual crab angle is still shown correctly in the tooltip
    if crab_angle and crab_exaggeration > 1.0:
        exaggerated_crab = crab_angle * crab_exaggeration
        # Calculate visual heading: start from track (heading - crab) and add exaggerated crab
        track = heading - crab_angle
        visual_heading = track + exaggerated_crab
    else:
        visual_heading = heading

    # Calculate wing scale factors based on bank angle
    # Positive bank = right turn (right wing down, appears shorter from above)
    # Negative bank = left turn (left wing down, appears shorter from above)
    bank_rad = math.radians(abs(bank_angle)) if bank_angle else 0

    # The "down" wing appears shorter due to perspective (cosine of bank angle)
    # At 45° bank, the down wing appears ~70% length
    down_scale = math.cos(bank_rad)
    up_scale = 1.0  # Up wing stays full length

    # Determine which wing is down based on bank direction
    if bank_angle and bank_angle > 0:  # Right bank - right wing down
        left_scale = up_scale
        right_scale = down_scale
    elif bank_angle and bank_angle < 0:  # Left bank - left wing down
        left_scale = down_scale
        right_scale = up_scale
    else:  # Wings level
        left_scale = 1.0
        right_scale = 1.0

    # Calculate scaled wing positions
    # Left wing: from x=46 extends to x=12 (34 pixels), tip at 8
    left_wing_end = 50 - (38 * left_scale)  # Main wing end
    left_wing_tip = 50 - (42 * left_scale)  # Wing tip
    left_stab_end = 50 - (22 * left_scale)  # Stabilizer end
    left_lex_end = 50 - (15 * left_scale)   # LEX end

    # Right wing: from x=54 extends to x=88 (34 pixels), tip at 92
    right_wing_end = 50 + (38 * right_scale)
    right_wing_tip = 50 + (42 * right_scale)
    right_stab_end = 50 + (22 * right_scale)
    right_lex_end = 50 + (15 * right_scale)

    # F-18 Super Hornet style SVG with bank-adjusted wings
    svg_airplane = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="36" height="36">
        <g transform="rotate({visual_heading}, 50, 50)">
            <!-- Main fuselage -->
            <path d="M50,8 L54,25 L54,75 L50,88 L46,75 L46,25 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1.5"/>

            <!-- Nose cone -->
            <path d="M50,8 L53,20 L47,20 Z" fill="#e8e8e8" stroke="#333333" stroke-width="1"/>

            <!-- Cockpit canopy -->
            <ellipse cx="50" cy="26" rx="3.5" ry="7" fill="#74b9ff" stroke="#0984e3" stroke-width="1"/>

            <!-- Leading Edge Extensions (LEX) -->
            <path d="M46,30 L{left_lex_end:.1f},48 L46,45 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1"/>
            <path d="M54,30 L{right_lex_end:.1f},48 L54,45 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1"/>

            <!-- Main wings (swept delta style) - scaled by bank -->
            <path d="M46,42 L{left_wing_end:.1f},62 L{left_wing_end + 2:.1f},66 L46,55 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1.2"/>
            <path d="M54,42 L{right_wing_end:.1f},62 L{right_wing_end - 2:.1f},66 L54,55 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1.2"/>

            <!-- Wing tips -->
            <path d="M{left_wing_end:.1f},62 L{left_wing_tip:.1f},64 L{left_wing_end + 2:.1f},66 Z" fill="#e8e8e8" stroke="#333333" stroke-width="0.8"/>
            <path d="M{right_wing_end:.1f},62 L{right_wing_tip:.1f},64 L{right_wing_end - 2:.1f},66 Z" fill="#e8e8e8" stroke="#333333" stroke-width="0.8"/>

            <!-- Horizontal stabilizers -->
            <path d="M46,72 L{left_stab_end:.1f},82 L{left_stab_end + 2:.1f},85 L46,78 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1"/>
            <path d="M54,72 L{right_stab_end:.1f},82 L{right_stab_end - 2:.1f},85 L54,78 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1"/>

            <!-- Twin vertical tails (canted outward like F-18) -->
            <path d="M44,65 L38,62 L40,78 L46,78 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1"/>
            <path d="M56,65 L62,62 L60,78 L54,78 Z" fill="#d0d0d0" stroke="#333333" stroke-width="1"/>

            <!-- Engine exhausts -->
            <ellipse cx="47" cy="86" rx="2.5" ry="3" fill="#fd79a8" stroke="#e84393" stroke-width="0.8"/>
            <ellipse cx="53" cy="86" rx="2.5" ry="3" fill="#fd79a8" stroke="#e84393" stroke-width="0.8"/>

            <!-- Afterburner glow -->
            <ellipse cx="47" cy="89" rx="1.5" ry="2" fill="#ffeaa7" opacity="0.8"/>
            <ellipse cx="53" cy="89" rx="1.5" ry="2" fill="#ffeaa7" opacity="0.8"/>
        </g>
    </svg>'''

    # Encode SVG as base64 data URL
    svg_base64 = base64.b64encode(svg_airplane.encode('utf-8')).decode('utf-8')
    icon_url = f"data:image/svg+xml;base64,{svg_base64}"

    # Create custom icon
    airplane_icon = {
        "iconUrl": icon_url,
        "iconSize": [36, 36],
        "iconAnchor": [18, 18],  # Center of the icon
    }

    marker = dl.Marker(
        position=pos,
        icon=airplane_icon,
        children=dl.Tooltip(
            tooltip_content,
            permanent=True,
            direction="right",
            offset=[22, 0],
            className="scrubber-tooltip"
        ),
    )

    return marker


# ============================================================
# Callbacks
# ============================================================
def register(app):
    """Install every map-interaction callback against the given Dash app."""

    @app.callback(
        Output("active-click-target", "data", allow_duplicate=True),
        Input({"type": "click-button", "m_id": ALL, "role": ALL}, "n_clicks"),
        State("maneuver-select", "value"),
        prevent_initial_call=True
    )
    def set_active_click_target(n_clicks_list, maneuver):
        if not ctx.triggered_id:
            raise PreventUpdate

        trig = ctx.triggered_id  # dict: {type, m_id, role}
        if not isinstance(trig, dict):
            raise PreventUpdate

        # Only accept clicks for the currently selected maneuver
        if trig.get("m_id") != maneuver:
            raise PreventUpdate

        return {"m_id": trig.get("m_id"), "role": trig.get("role")}

    @app.callback(
        Output({"type": "click-status", "m_id": MATCH}, "children", allow_duplicate=True),
        Input({"type": "click-button", "m_id": MATCH, "role": ALL}, "n_clicks"),
        prevent_initial_call=True
    )
    def show_click_prompt(n_clicks_list):
        ctx_local = dash.callback_context
        if not ctx_local.triggered:
            raise PreventUpdate

        triggered_id = ctx_local.triggered_id
        role = triggered_id.get("role")
        return f"Click on the map to set the {role.replace('_', ' ')} point."

    @app.callback(
        Output({"type": "point-store", "m_id": ALL, "role": ALL}, "data", allow_duplicate=True),
        Output("active-click-target", "data", allow_duplicate=True),
        Output("layer", "children", allow_duplicate=True),
        Output("click_debug", "children", allow_duplicate=True),
        Output("last-click-info", "data"),
        Input("map", "clickData"),
        State("active-click-target", "data"),
        State({"type": "point-store", "m_id": ALL, "role": ALL}, "id"),
        State({"type": "point-store", "m_id": ALL, "role": ALL}, "data"),
        State("layer", "children"),
        State("pylons-ias-store", "data"),
        State("pylons-bank-store", "data"),
        State("env-wind-speed", "value"),
        prevent_initial_call=True
    )
    def write_point_to_scoped_store(click, target, store_ids, store_data, layer_children, pylons_ias, pylons_bank, wind_speed):
        if not click or "latlng" not in click or not isinstance(target, dict):
            raise PreventUpdate

        m_id = target.get("m_id")
        role = target.get("role")
        if not m_id or not role:
            raise PreventUpdate

        lat = click["latlng"]["lat"]
        lon = click["latlng"]["lng"]
        elev = get_elevation(lat, lon)

        # Minimum pylon distance enforcement for Eights on Pylons
        # Distance is calculated based on turn radius = 2 × radius so circles don't overlap
        # Turn radius R = V² / (g × tan(bank)), where V is groundspeed in ft/s
        min_pylon_distance_warning = None

        if m_id == "pylons" and role == "pylon_b":
            import math

            # Calculate dynamic minimum distance based on aircraft performance
            ias_kt = float(pylons_ias) if pylons_ias else 100
            bank_deg = float(pylons_bank) if pylons_bank else 30
            wind_kt = float(wind_speed) if wind_speed else 0

            # Approximate groundspeed (worst case: direct tailwind adds to speed)
            gs_kt = ias_kt + wind_kt
            gs_fps = gs_kt * 1.68781  # Convert to ft/s

            # Turn radius: R = V² / (g × tan(bank))
            g_fps2 = 32.174
            bank_rad = math.radians(bank_deg)
            if bank_rad > 0.01:  # Avoid division by zero
                turn_radius_ft = (gs_fps ** 2) / (g_fps2 * math.tan(bank_rad))
            else:
                turn_radius_ft = 10000  # Large default if bank is near zero

            # Minimum distance = 2 × turn radius (so circles just touch)
            # Add 10% margin for realistic transition
            min_distance_ft = turn_radius_ft * 2.2
            MIN_PYLON_DISTANCE_NM = min_distance_ft / 6076.12

            # Find pylon_a data to check distance
            pylon_a_data = None
            for i, sid in enumerate(store_ids):
                if isinstance(sid, dict) and sid.get("m_id") == "pylons" and sid.get("role") == "pylon_a":
                    pylon_a_data = store_data[i]
                    break

            if pylon_a_data and pylon_a_data.get("lat") and pylon_a_data.get("lon"):
                from geopy import Point as GeoPoint
                from geopy.distance import distance as geo_dist
                from physics import calculate_initial_compass_bearing, point_from

                pylon_a_geo = GeoPoint(pylon_a_data["lat"], pylon_a_data["lon"])
                clicked_geo = GeoPoint(lat, lon)

                # Calculate distance between pylons
                dist_nm = geo_dist(pylon_a_geo, clicked_geo).nm

                if dist_nm < MIN_PYLON_DISTANCE_NM:
                    # Clicked too close - move pylon_b to minimum distance along the clicked bearing
                    bearing = calculate_initial_compass_bearing(pylon_a_geo, clicked_geo)
                    adjusted_pt = point_from(pylon_a_geo, bearing, MIN_PYLON_DISTANCE_NM)
                    lat = adjusted_pt.latitude
                    lon = adjusted_pt.longitude
                    elev = get_elevation(lat, lon)
                    min_pylon_distance_warning = f"Min {MIN_PYLON_DISTANCE_NM:.2f} NM for {ias_kt:.0f}kt/{bank_deg:.0f}° (clicked {dist_nm:.2f} NM)"

        new_pt = {"lat": lat, "lon": lon, "elevation_ft": elev}

        # ----- write to the correct scoped store -----
        updated = list(store_data)  # same order as store_ids
        wrote = False
        for i, sid in enumerate(store_ids):
            if isinstance(sid, dict) and sid.get("m_id") == m_id and sid.get("role") == role:
                updated[i] = new_pt
                wrote = True
                break

        if not wrote:
            raise PreventUpdate

        # ----- immediate marker on the map -----
        layer_children = layer_children or []

        marker_id = {"type": "pt-marker", "m_id": m_id, "role": role}

        kept = []
        for child in layer_children:
            try:
                # Drop any existing marker for this exact (m_id, role)
                if getattr(child, "id", None) != marker_id:
                    kept.append(child)
            except Exception:
                kept.append(child)

        # Color convention
        color = "green"
        if role == "touchdown":
            color = "red"
        elif role in ("impact", "failure", "engine_failure"):
            color = "black"
        elif role in ("ref", "reference", "center"):
            color = "blue"
        elif role in ("entry", "start"):
            color = "green"
        elif role == "dw_start":
            color = "green"
        elif role == "dw_end":
            color = "orange"

        marker = dl.CircleMarker(
            id=marker_id,
            center=[lat, lon],
            radius=7,
            color=color,
            fill=True,
            fillOpacity=1.0,
            children=dl.Tooltip(f"{m_id} {role}: {lat:.5f}, {lon:.5f}")
        )

        new_layer = kept + [marker]

        # Click confirmation feedback (minimal)
        role_display = role.replace("_", " ").title()
        if min_pylon_distance_warning:
            # Show warning when pylon was adjusted due to minimum distance
            feedback = html.Div([
                html.Div([
                    html.Span("!", style={"color": "#e67e22", "fontSize": "8px", "marginRight": "3px", "fontWeight": "bold"}),
                    html.Span(min_pylon_distance_warning, style={"fontSize": "8px", "color": "#e67e22"}),
                ]),
                html.Div([
                    html.Span("", style={"color": "#aaa", "fontSize": "6px", "marginRight": "2px"}),
                    html.Span(f"{role_display} adjusted: {lat:.4f}, {lon:.4f}", style={"fontSize": "7px", "color": "#999"}),
                ]),
            ], style={"padding": "1px 0", "marginTop": "1px", "lineHeight": "1.2"})
        else:
            feedback = html.Div([
                html.Span("", style={"color": "#aaa", "fontSize": "6px", "marginRight": "2px"}),
                html.Span(f"{role_display}: {lat:.4f}, {lon:.4f}", style={"fontSize": "7px", "color": "#999"}),
            ], style={"padding": "1px 0", "marginTop": "1px", "lineHeight": "1"})

        # Save last click info for undo
        last_click = {"m_id": m_id, "role": role, "store_index": None}
        for i, sid in enumerate(store_ids):
            if isinstance(sid, dict) and sid.get("m_id") == m_id and sid.get("role") == role:
                last_click["store_index"] = i
                break

        # Clear target after one successful click so extra clicks don't overwrite
        return updated, None, new_layer, feedback, last_click

    @app.callback(
        Output({"type": "click-status", "m_id": MATCH}, "children", allow_duplicate=True),
        Input({"type": "point-store", "m_id": MATCH, "role": ALL}, "data"),
        State({"type": "point-store", "m_id": MATCH, "role": ALL}, "id"),
        prevent_initial_call=True
    )
    def summarize_points(points, ids):
        parts = []
        for pid, pdata in zip(ids, points):
            role = pid.get("role", "point").replace("_", " ")
            if isinstance(pdata, dict) and pdata.get("lat") is not None and pdata.get("lon") is not None:
                lat = pdata["lat"]
                lon = pdata["lon"]
                elev = pdata.get("elevation_ft")
                if role == "touchdown" and elev is not None:
                    parts.append(f"{role} set ({lat:.4f}, {lon:.4f}) elev {int(round(elev))} ft")
                else:
                    parts.append(f"{role} set ({lat:.4f}, {lon:.4f})")
            else:
                parts.append(f"⬜ {role} not set")
        return " | ".join(parts)

    @app.callback(
        Output({"type": "point-store", "m_id": ALL, "role": ALL}, "data", allow_duplicate=True),
        Output("layer", "children", allow_duplicate=True),
        Output("click_debug", "children", allow_duplicate=True),
        Output("last-click-info", "data", allow_duplicate=True),
        Input("undo-last-click", "n_clicks"),
        State("last-click-info", "data"),
        State({"type": "point-store", "m_id": ALL, "role": ALL}, "id"),
        State({"type": "point-store", "m_id": ALL, "role": ALL}, "data"),
        State("layer", "children"),
        prevent_initial_call=True
    )
    def undo_last_click(n_clicks, last_click, store_ids, store_data, layer_children):
        """Undo the last point that was clicked."""
        if not n_clicks or not last_click:
            raise PreventUpdate

        m_id = last_click.get("m_id")
        role = last_click.get("role")
        if not m_id or not role:
            raise PreventUpdate

        # Clear the point store for the last click
        updated = list(store_data)
        for i, sid in enumerate(store_ids):
            if isinstance(sid, dict) and sid.get("m_id") == m_id and sid.get("role") == role:
                updated[i] = None
                break

        # Remove marker from layer
        marker_id = {"type": "pt-marker", "m_id": m_id, "role": role}
        layer_children = layer_children or []
        new_layer = [c for c in layer_children if getattr(c, "id", None) != marker_id]

        # Feedback (minimal)
        role_display = role.replace("_", " ").title()
        feedback = html.Div([
            html.Span("↩", style={"color": "#aaa", "fontSize": "6px", "marginRight": "2px"}),
            html.Span(f"{role_display} cleared", style={"color": "#999", "fontSize": "7px"}),
        ], style={"padding": "1px 0", "marginTop": "1px", "lineHeight": "1"})

        return updated, new_layer, feedback, None

    @app.callback(
        Output("engineout-manual-elev", "value"),
        Input({"type": "point-store", "m_id": "engineout", "role": "touchdown"}, "data"),
        State("maneuver-select", "value"),
        prevent_initial_call=True
    )
    def autofill_engineout_touchdown_elev(td_data, maneuver):
        if maneuver != "engineout":
            raise PreventUpdate
        if not isinstance(td_data, dict):
            raise PreventUpdate

        elev = td_data.get("elevation_ft")
        if elev is None:
            raise PreventUpdate

        return int(round(elev))

    @app.callback(
        Output("click_debug", "children"),
        Input("map", "clickData"),
        prevent_initial_call=True
    )
    def display_click_location(click):
        if not click or "latlng" not in click:
            raise dash.exceptions.PreventUpdate

        lat = click["latlng"]["lat"]
        lon = click["latlng"]["lng"]
        return f"Location clicked: {lat:.5f}, {lon:.5f}"
